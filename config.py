import os
from dotenv import load_dotenv

load_dotenv()

USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
HF_TOKENS = os.getenv("HF_TOKENS", "").split(",")
API_KEY = os.getenv('API_KEY')

if not USERNAME or not PASSWORD or not HF_TOKENS or not API_KEY:
    raise Exception("请在 .env 文件中配置 USERNAME、PASSWORD、HF_TOKENS 和 API_KEY")
