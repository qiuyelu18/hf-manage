from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, disconnect
from dotenv import load_dotenv
from huggingface_hub import HfApi
from functools import wraps
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from config import USERNAME, PASSWORD, HF_TOKENS
from api import api as api_blueprint
import concurrent.futures
import threading
import logging
import time
import os

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.register_blueprint(api_blueprint)
socketio = SocketIO(app)

# 缓存管理
class SpaceCache:
    def __init__(self):
        self.spaces = {}
        self.last_update = None
        self.lock = threading.Lock()
        self.active_clients = set()  # 跟踪活动的客户端

    def update_all(self, spaces_data):
        with self.lock:
            self.spaces = {space['repo_id']: space for space in spaces_data}
            self.last_update = datetime.now()

    def get_all(self):
        with self.lock:
            return list(self.spaces.values()) if self.spaces else []

    def is_expired(self, expire_minutes=5):
        if not self.last_update:
            return True
        return datetime.now() - self.last_update > timedelta(minutes=expire_minutes)

    def add_client(self, client_id):
        with self.lock:
            self.active_clients.add(client_id)

    def remove_client(self, client_id):
        with self.lock:
            self.active_clients.discard(client_id)

    def has_active_clients(self):
        with self.lock:
            return len(self.active_clients) > 0

space_cache = SpaceCache()

# WebSocket 事件处理
@socketio.on('connect')
def handle_connect():
    if 'authenticated' not in session or not session['authenticated']:
        disconnect()
        return

    client_id = request.sid
    space_cache.add_client(client_id)
    logger.info(f"Client connected: {client_id}")

@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.sid
    space_cache.remove_client(client_id)
    logger.info(f"Client disconnected: {client_id}")

# 登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'authenticated' not in session or not session['authenticated']:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def process_single_space(space, hf_api, username, token):
    try:
        space_info = hf_api.space_info(repo_id=space.id)
        space_runtime = space_info.runtime
        
        status = "未知状态"
        if space_runtime:
            status = space_runtime.stage if hasattr(space_runtime, 'stage') else "未知状态"

        return {
            "repo_id": space_info.id,
            "name": space_info.cardData.get('title') or space_info.id.split('/')[-1],
            "owner": space_info.author,
            "username": username,
            "token": token,
            "url": f"https://{space_info.author}-{space_info.id.split('/')[-1]}.hf.space",
            "status": status,
            "last_modified": space_info.lastModified.strftime("%Y-%m-%d %H:%M:%S") if space_info.lastModified else "未知",
            "created_at": space_info.created_at.strftime("%Y-%m-%d %H:%M:%S") if space_info.created_at else "未知",
            "sdk": space_info.sdk,
            "tags": space_info.tags,
            "private": space_info.private,
            "app_port": space_info.cardData.get('app_port', '未知')
        }
    except Exception as e:
        logger.error(f"处理 Space {space.id} 时出错: {e}")
        return None

def get_all_user_spaces():
    # 检查缓存是否有效
    if not space_cache.is_expired():
        logger.info("从缓存获取 Spaces 数据")
        return space_cache.get_all()

    all_spaces = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        for token in HF_TOKENS:
            try:
                hf_api = HfApi(token=token)
                user_info = hf_api.whoami()
                username = user_info["name"]
                logger.info(f"获取到用户信息: {username}")

                spaces = list(hf_api.list_spaces(author=username))
                logger.info(f"获取到 {len(spaces)} 个 Spaces")

                # 并行处理每个space
                future_to_space = {
                    executor.submit(process_single_space, space, hf_api, username, token): space 
                    for space in spaces
                }

                for future in concurrent.futures.as_completed(future_to_space):
                    space_data = future.result()
                    if space_data:
                        all_spaces.append(space_data)

            except Exception as e:
                logger.error(f"获取 Spaces 列表失败 (token: {token[:5]}...): {e}")
                import traceback
                traceback.print_exc()

    # 按名称排序
    all_spaces.sort(key=lambda x: x['name'].lower())
    
    # 更新缓存
    space_cache.update_all(all_spaces)
    
    logger.info(f"总共获取到 {len(all_spaces)} 个 Spaces")
    return all_spaces

# 后台更新缓存的函数
def update_cache_if_needed():
    """在有活动客户端时更新缓存"""
    while True:
        try:
            if space_cache.has_active_clients() and space_cache.is_expired():
                logger.info("Updating cache due to active clients")
                spaces = get_all_user_spaces()
                space_cache.update_all(spaces)
                socketio.emit('spaces_updated', {'timestamp': time.time()})
        except Exception as e:
            logger.error(f"Cache update failed: {e}")
        time.sleep(60)  # 每分钟检查一次

# 启动缓存更新线程
update_thread = threading.Thread(target=update_cache_if_needed, daemon=True)
update_thread.start()

@app.route("/", methods=["GET", "POST"])
def login():
    if 'authenticated' in session and session['authenticated']:
        return redirect(url_for('dashboard'))
    
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == USERNAME and password == PASSWORD:
            session['authenticated'] = True
            return redirect(url_for("dashboard"))
        else:
            return render_template("index.html", error="用户名或密码错误")
    return render_template("index.html", error=None)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/dashboard")
@login_required
def dashboard():
    spaces = get_all_user_spaces()
    logger.info(f"Dashboard 显示 {len(spaces)} 个 Spaces")
    return render_template("dashboard.html", spaces=spaces)

@app.route("/api/space/<path:repo_id>/status")
@login_required
def get_space_status(repo_id):
    spaces = get_all_user_spaces()
    space = next((s for s in spaces if s["repo_id"] == repo_id), None)
    if not space:
        return jsonify({"error": "Space not found"}), 404
    return jsonify({
        "id": repo_id,
        "status": space["status"]
    })

def restart_space(repo_id, token):
    try:
        hf_api = HfApi(token=token)
        hf_api.restart_space(repo_id=repo_id)
        return f"成功重启 Space: {repo_id}"
    except Exception as e:
        return f"重启 Space {repo_id} 失败: {e}"
    
def rebuild_space(repo_id, token):
    try:
        hf_api = HfApi(token=token)
        hf_api.restart_space(repo_id=repo_id, factory_reboot=True)
        return f"成功重建 Space: {repo_id}"
    except Exception as e:
        return f"重建 Space {repo_id} 失败: {e}"

@app.route("/action/<action_type>/<path:repo_id>")
@login_required
def space_action(action_type, repo_id):
    spaces = get_all_user_spaces()
    space = next((s for s in spaces if s["repo_id"] == repo_id), None)
    
    if not space:
        return "Space not found", 404
    
    if action_type == "restart":
        message = restart_space(repo_id, space["token"])
    elif action_type == "rebuild":
        message = rebuild_space(repo_id, space["token"])
    else:
        message = "未知操作"
    return render_template("action_result.html", message=message)

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000)
