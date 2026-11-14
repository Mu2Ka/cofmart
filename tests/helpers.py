import hashlib
import hmac
import json
import time
from urllib.parse import urlencode


TOKEN = "123456:test-token-for-unit-tests-only"


def init_data(user_id=1001, timestamp=None, **extra):
    data = {
        "auth_date": str(int(time.time()) if timestamp is None else timestamp),
        "user": json.dumps({"id": user_id, "first_name": "Тест"}, ensure_ascii=False),
        "query_id": "test-query",
        **extra,
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)
