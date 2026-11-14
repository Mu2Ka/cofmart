import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class InvalidInitData(ValueError):
    pass


def validate_init_data(raw: str, bot_token: str, max_age: int, *, now: int | None = None) -> int:
    """Verify the exact Telegram initData string before trusting the user ID."""
    if not bot_token or not raw or len(raw) > 16384:
        raise InvalidInitData("Invalid initData")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        data = dict(pairs)
        if len(pairs) != len(data):
            raise ValueError("Duplicate keys")
        received_hash = data.pop("hash")
        if len(received_hash) != 64:
            raise ValueError("Invalid hash")
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            raise ValueError("Invalid signature")
        timestamp = int(data["auth_date"])
        current = int(time.time()) if now is None else now
        if timestamp > current + 30 or current - timestamp > max_age:
            raise ValueError("Expired initData")
        user = json.loads(data["user"])
        telegram_id = user["id"]
        if type(telegram_id) is not int or not 0 < telegram_id < 2**63:
            raise ValueError("Invalid user")
        return telegram_id
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise InvalidInitData("Invalid or expired initData") from exc
