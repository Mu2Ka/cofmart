import os
from pathlib import Path
from app.config import get_settings


def mini_app_url():
    if os.getenv('COFMART_LOCAL_RUNTIME') == '1':
        path = Path(__file__).resolve().parents[2] / '.local' / 'mini-app-url.txt'
        if path.exists():
            return path.read_text(encoding='utf-8').strip()
    return get_settings().mini_app_url
