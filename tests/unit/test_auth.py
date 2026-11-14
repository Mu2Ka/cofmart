import pytest
from aiogram.utils.web_app import check_webapp_signature

from app.api.auth import InvalidInitData, validate_init_data
from tests.helpers import TOKEN, init_data


def test_valid_signature_matches_aiogram():
    raw = init_data(timestamp=10000)
    assert check_webapp_signature(TOKEN, raw)
    assert validate_init_data(raw, TOKEN, 3600, now=10001) == 1001


@pytest.mark.parametrize("raw", [
    "", "user=bad", init_data(timestamp=1), init_data(timestamp=20000),
    init_data(timestamp=10000).replace("10000", "10001"),
    init_data(timestamp=10000) + "&auth_date=10000",
    init_data(user_id=True, timestamp=10000), init_data(user_id=-1, timestamp=10000),
    init_data(user_id="1001", timestamp=10000),
])
def test_rejects_invalid_auth(raw):
    with pytest.raises(InvalidInitData):
        validate_init_data(raw, TOKEN, 3600, now=10001)
