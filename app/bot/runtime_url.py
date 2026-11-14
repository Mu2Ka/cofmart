import os
from pathlib import Path
from dotenv import load_dotenv
from app.config import ENV_PATH


def mini_app_url():
    if os.getenv('COFMART_LOCAL_RUNTIME') == '1':
        path = Path(__file__).resolve().parents[2] / '.local' / 'mini-app-url.txt'
        if path.exists():
            return path.read_text(encoding='utf-8').strip()
    load_dotenv(ENV_PATH)
    return os.getenv('MINI_APP_URL', '')
