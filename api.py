from flask import Blueprint, request, jsonify
from functools import wraps
from huggingface_hub import HfApi
from config import API_KEY

api = Blueprint('api', __name__, url_prefix='/api/v1')

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'No Authorization header'}), 401
        
        try:
            scheme, token = auth_header.split()
            if scheme.lower() != 'bearer':
                return jsonify({'error': 'Invalid authorization scheme'}), 401
            if token != API_KEY:
                return jsonify({'error': 'Invalid API key'}), 401
        except ValueError:
            return jsonify({'error': 'Invalid Authorization header format'}), 401
        
        return f(*args, **kwargs)
    return decorated

@api.route('/info/<token>', methods=['GET'])
@require_api_key
def list_spaces(token):
    """列出所有空间"""
    try:
        hf_api = HfApi(token=token)
        # 验证token
        try:
            user_info = hf_api.whoami()
            username = user_info["name"]
        except Exception:
            return jsonify({'error': 'Invalid HuggingFace token'}), 401

        spaces = list(hf_api.list_spaces(author=username))
        space_list = []
        
        for space in spaces:
            try:
                space_info = hf_api.space_info(repo_id=space.id)
                space_list.append(space_info.id)
            except Exception as e:
                continue

        return jsonify({
            'spaces': space_list,
            'total': len(space_list)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/info/<token>/<path:space_id>', methods=['GET'])
@require_api_key
def get_space_info(token, space_id):
    """获取特定空间信息"""
    try:
        hf_api = HfApi(token=token)
        try:
            space_info = hf_api.space_info(repo_id=space_id)
        except Exception:
            return jsonify({'error': 'Space not found'}), 404

        # 获取运行状态
        status = "未知状态"
        if space_info.runtime:
            status = space_info.runtime.stage if hasattr(space_info.runtime, 'stage') else "未知状态"

        return jsonify({
            'id': space_info.id,
            'status': status,
            'last_modified': space_info.lastModified.isoformat() if space_info.lastModified else None,
            'created_at': space_info.created_at.isoformat() if space_info.created_at else None,
            'sdk': space_info.sdk,
            'tags': space_info.tags,
            'private': space_info.private
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/action/<token>/<path:space_id>/restart', methods=['POST'])
@require_api_key
def restart_space(token, space_id):
    """重启空间"""
    try:
        hf_api = HfApi(token=token)
        try:
            hf_api.restart_space(repo_id=space_id)
            return jsonify({
                'success': True,
                'message': f'Space {space_id} restart initiated successfully'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api.route('/action/<token>/<path:space_id>/rebuild', methods=['POST'])
@require_api_key
def rebuild_space(token, space_id):
    """重建空间"""
    try:
        hf_api = HfApi(token=token)
        try:
            hf_api.restart_space(repo_id=space_id, factory_reboot=True)
            return jsonify({
                'success': True,
                'message': f'Space {space_id} rebuild initiated successfully'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
