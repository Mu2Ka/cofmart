import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.config import Settings
from app.services.dto import ItemInput, OrderCommand
from app.services.orders import OrderService
from tests.helpers import TOKEN, init_data


@pytest.fixture
async def client(db):
    app = create_app(Settings("sqlite+aiosqlite://", bot_token=TOKEN, cors_origins=("https://mini.example",)), db)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client


async def test_api_requires_verified_telegram(client):
    for path in ["/cafes", "/cafes/1/menu", "/cafes/1/slots", "/orders"]:
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers={"Authorization": "tma broken"})).status_code == 401
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_api_order_visible_in_shared_service_and_vice_versa(client, db):
    headers = {"Authorization": f"tma {init_data()}"}
    assert len((await client.get("/cafes", headers=headers)).json()) == 2
    assert (await client.get("/cafes/1/menu", headers=headers)).json()[0]["name"] == "Бамбл"
    assert len((await client.get("/cafes/1/slots", headers=headers)).json()) == 1
    cart = {"cafe_id": 1, "items": [{"menu_item_id": 1, "quantity": 2}]}
    preview = await client.post("/orders/preview", headers=headers, json=cart)
    assert preview.json()["total_minor"] == 57000
    payload = {**cart, "slot_id": 1, "expected_total_minor": 57000, "idempotency_key": "api-1"}
    response = await client.post("/orders", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    order = response.json()
    assert (await client.post("/orders", headers=headers, json=payload)).json()["id"] == order["id"]
    service = OrderService(db.sessions)
    assert (await service.get(1001, order["id"])).total_minor == 57000
    bot_order = await service.create(1001, OrderCommand(1, 1, [ItemInput(2, 1)], 16000, "bot-1"))
    history = (await client.get("/orders", headers=headers)).json()
    assert {x["id"] for x in history} == {order["id"], bot_order.id}
    other = {"Authorization": f"tma {init_data(user_id=1002)}"}
    assert (await client.get(f'/orders/{order["id"]}', headers=other)).status_code == 404


async def test_client_cannot_override_owner_or_price(client):
    headers = {"Authorization": f"tma {init_data()}"}
    payload = {"cafe_id": 1, "slot_id": 1, "items": [{"menu_item_id": 1, "quantity": 1}],
               "expected_total_minor": 1, "idempotency_key": "bad-price"}
    response = await client.post("/orders", headers=headers, json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "PRICE_CHANGED"
    assert (await client.post("/orders", headers=headers, json={**payload, "user_id": 999})).status_code == 422
    assert (await client.post("/orders", headers=headers, json={**payload, "items": [{"menu_item_id": 1, "quantity": True}]})).status_code == 422


async def test_cors_is_explicit(client):
    headers = {"Origin": "https://mini.example", "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "authorization,content-type"}
    assert (await client.options("/orders", headers=headers)).headers["access-control-allow-origin"] == "https://mini.example"
    response = await client.options("/orders", headers={**headers, "Origin": "https://other.example"})
    assert "access-control-allow-origin" not in response.headers
