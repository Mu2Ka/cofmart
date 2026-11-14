from unittest.mock import AsyncMock
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import create_app
from app.config import Settings
from app.db.order_store import PostgresStore
from app.ordering import settings
from app.ordering.seed import seed
from tests.helpers import TOKEN, init_data
from tests.integration.test_postgres import pgdb

pytestmark = pytest.mark.postgres


@pytest.fixture
async def full_client(pgdb, monkeypatch):
    monkeypatch.setattr(settings, 'FOLLOW_SCHEDULE', False)
    monkeypatch.setattr(settings, 'ADMIN_IDS', {9001})
    monkeypatch.setattr(settings, 'BARISTA_CAFES', {9002: {'1'}})
    monkeypatch.setattr('app.api.routers.flow.notification', AsyncMock())
    await seed(pgdb.sessions)
    app = create_app(Settings('postgresql+asyncpg://unused@localhost/test', bot_token=TOKEN), pgdb)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            yield client


def headers(uid=1001):
    return {'Authorization': 'tma ' + init_data(user_id=uid)}


async def perform(client, action, uid=1001, expected=200, **values):
    response = await client.post('/flow/action', headers=headers(uid), json={'action': action, **values})
    assert response.status_code == expected, response.text
    return response.json()


async def test_variants_comment_favorites_repeat_rating_and_staff(full_client, pgdb):
    client = full_client
    state = (await client.get('/flow/state', headers=headers())).json()
    assert (await client.post('/flow/action', headers=headers(), json={'action':'prepare','price':1})).status_code == 422
    assert len(state['cafes'][0]['products']) == 38
    latte = next(p for p in state['cafes'][0]['products'] if p['id'] == '4')
    assert latte['variants']['4_350a']['price'] == 330
    session = (await perform(client, 'begin'))['result']
    draft = (await perform(client, 'prepare', cafe_id='1', drink_id='4_350a',
                           break_id=state['periods'][0]['id'], session=session))['result']
    draft = (await perform(client, 'comment', token=draft['token'], comment='Без сахара'))['result']
    await perform(client, 'favorite_draft', token=draft['token'])
    order = (await perform(client, 'confirm', token=draft['token']))['result']
    again = (await perform(client, 'confirm', token=draft['token']))['result']
    assert order['number'] == again['number']
    assert order['draft']['comment'] == 'Без сахара'
    # The bot uses this same store, not a second implementation of order rules.
    store = PostgresStore(pgdb.sessions)
    assert (await store.call('orders', 'for_user', 1001))[0].number == order['number']
    await perform(client, 'transition', uid=1001, expected=403, reference=order['reference'], status='preparing', revision=0)
    for revision, status in enumerate(['preparing','ready','done']):
        await perform(client, 'transition', uid=9002, reference=order['reference'], status=status, revision=revision)
    await perform(client, 'rate', reference=order['reference'], value=5)
    await perform(client, 'rate', uid=1002, expected=409, reference=order['reference'], value=1)
    draft = (await perform(client, 'repeat', reference=order['reference']))['result']
    assert draft['comment'] == 'Без сахара'
    state = (await client.get('/flow/state', headers=headers())).json()
    assert len(state['favorites']) == 1
    await perform(client, 'cancel', session=state['session'])
    draft = (await perform(client, 'favorite_prepare', key=state['favorites'][0]['key']))['result']
    assert draft['comment'] == ''
    await perform(client, 'favorite_remove', key=state['favorites'][0]['key'])
    staff = (await client.get('/flow/staff/1', headers=headers(9002))).json()
    assert staff['rating_average'] == 5
    assert (await client.get('/flow/staff/2', headers=headers(9002))).status_code == 403


async def test_staff_admin_limits_stoplist_and_permissions(full_client):
    client = full_client
    await perform(client, 'assign', expected=403, cafe_id='1', target_id=1001, enabled=True)
    await perform(client, 'assign', uid=9001, cafe_id='1', target_id=1001, enabled=True)
    staff = (await client.get('/flow/staff/1', headers=headers())).json()
    period = staff['periods'][0]
    await perform(client, 'add_slots', cafe_id='1', break_id=period['id'], value=5, revision=period['revision'])
    await perform(client, 'add_slots', expected=409, cafe_id='1', break_id=period['id'], value=5, revision=period['revision'])
    await perform(client, 'set_available', cafe_id='1', product_id='4', enabled=False)
    session = (await perform(client, 'begin'))['result']
    await perform(client, 'prepare', expected=409, cafe_id='1', drink_id='4_350', break_id=period['id'], session=session)
    await perform(client, 'set_open', cafe_id='1', enabled=False)
    await perform(client, 'prepare', expected=409, cafe_id='1', drink_id='1_350', break_id=period['id'], session=session)
    await perform(client, 'assign', uid=9001, cafe_id='1', target_id=1001, enabled=False)
    assert (await client.get('/flow/staff/1', headers=headers())).status_code == 403


async def test_atomic_reservation_of_last_slot(full_client):
    client = full_client
    state = (await client.get('/flow/state', headers=headers())).json()
    period = state['periods'][0]['id']
    staff = (await client.get('/flow/staff/1', headers=headers(9002))).json()
    revision = staff['periods'][0]['revision']
    await perform(client, 'set_slots', uid=9002, cafe_id='1', break_id=period, value=1, revision=revision)
    sessions = [(uid, (await perform(client, 'begin', uid=uid))['result']) for uid in range(1001,1009)]
    responses = await asyncio.gather(*[client.post('/flow/action', headers=headers(uid), json={
        'action':'prepare', 'cafe_id':'1','drink_id':'1_350','break_id':period,'session':session,
    }) for uid,session in sessions])
    assert [r.status_code for r in responses].count(200) == 1
    assert [r.status_code for r in responses].count(409) == 7
    winner = next(i for i,r in enumerate(responses) if r.status_code==200)
    uid = sessions[winner][0]
    token = responses[winner].json()['result']['token']
    orders = await asyncio.gather(*[perform(client,'confirm',uid=uid,token=token) for _ in range(2)])
    assert orders[0]['result']['number'] == orders[1]['result']['number']
    staff = (await client.get('/flow/staff/1', headers=headers(9002))).json()
    assert staff['periods'][0]['free'] == 0
    assert staff['periods'][0]['confirmed'] == 1
    assert staff['periods'][0]['reserved'] == 0


async def test_blocked_user_cannot_open_mini_app(full_client, monkeypatch):
    monkeypatch.setattr(settings, 'BLOCKED_USER_IDS', {1001})
    response = await full_client.get('/flow/state', headers=headers())
    assert response.status_code == 403
    assert 'заблокированы' in response.json()['detail']
