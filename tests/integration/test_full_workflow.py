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
from datetime import datetime
from app.ordering.schedule import LOCAL_TIMEZONE
from sqlalchemy import event
from sqlalchemy import text
import os
from types import SimpleNamespace
from app.db.session import Database
from app.ordering.orders import Draft, OrderError
from app.ordering.schedule import local_now

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


async def test_blocked_user_cannot_bypass_policy_through_legacy_api(full_client, monkeypatch):
    monkeypatch.setattr(settings,'BLOCKED_USER_IDS',{1001})
    for path in ['/orders','/cafes','/cafes/1/menu','/cafes/1/slots','/flow/state']:
        response = await full_client.get(path,headers=headers())
        assert response.status_code == 403, (path,response.text)


async def test_comment_edit_is_atomic_can_clear_and_invalidates_old_confirmation(full_client):
    client = full_client
    state = (await client.get('/flow/state',headers=headers())).json()
    session = (await perform(client,'begin'))['result']
    draft = (await perform(client,'prepare',cafe_id='1',drink_id='1_350',
        break_id=state['periods'][0]['id'],session=session))['result']
    edited = (await perform(client,'comment',token=draft['token'],comment='🧊'*300))['result']
    assert edited['comment'] == '🧊'*300
    assert edited['reserved_until'] == draft['reserved_until']
    await perform(client,'confirm',token=draft['token'],expected=409)
    cleared = (await perform(client,'comment',token=edited['token'],comment=''))['result']
    assert cleared['comment'] == ''
    await perform(client,'confirm',token=cleared['token'])


async def test_cancel_stale_session_does_not_discard_new_draft(full_client):
    first = (await perform(full_client,'begin'))['result']
    second = (await perform(full_client,'begin'))['result']
    await perform(full_client,'cancel',session=first,expected=409)
    state = (await full_client.get('/flow/state',headers=headers())).json()
    assert state['session'] == second


async def test_rejected_shortcut_preserves_current_reservation(full_client):
    state = (await full_client.get('/flow/state',headers=headers())).json()
    session = (await perform(full_client,'begin'))['result']
    draft = (await perform(full_client,'prepare',cafe_id='1',drink_id='1_350',
        break_id=state['periods'][0]['id'],session=session))['result']
    await perform(full_client,'favorite_prepare',key='missing',expected=409)
    current = (await full_client.get('/flow/state',headers=headers())).json()
    assert current['draft']['token'] == draft['token']
    assert current['session'] == session


async def test_baristas_cannot_both_claim_same_revision(full_client,monkeypatch):
    monkeypatch.setattr(settings,'BARISTA_CAFES',{9002:{'1'},9003:{'1'}})
    state = (await full_client.get('/flow/state',headers=headers())).json()
    session = (await perform(full_client,'begin'))['result']
    draft = (await perform(full_client,'prepare',cafe_id='1',drink_id='1_350',
        break_id=state['periods'][0]['id'],session=session))['result']
    order = (await perform(full_client,'confirm',token=draft['token']))['result']
    replies = await asyncio.gather(*[full_client.post('/flow/action',headers=headers(uid),json={
        'action':'transition','reference':order['reference'],'status':'preparing','revision':0})
        for uid in (9002,9003)])
    assert sorted(reply.status_code for reply in replies) == [200,409]


async def test_http_pause_boundaries_preserve_history_and_staff_access(full_client, monkeypatch):
    monkeypatch.setattr(settings,'FOLLOW_SCHEDULE',True)
    clock = [datetime(2031,1,2,9,39,30,tzinfo=LOCAL_TIMEZONE)]
    monkeypatch.setattr('app.api.routers.flow.local_now',lambda:clock[0])
    state = (await full_client.get('/flow/state',headers=headers())).json()
    session = (await perform(full_client,'begin'))['result']
    draft = (await perform(full_client,'prepare',cafe_id='1',drink_id='1_350',
        break_id=state['periods'][0]['id'],session=session))['result']
    clock[0] = clock[0].replace(minute=40,second=0)
    paused = (await full_client.get('/flow/state',headers=headers())).json()
    assert paused['periods'] == [] and paused['draft'] is None
    await perform(full_client,'confirm',token=draft['token'],expected=409)
    assert (await full_client.get('/flow/staff/1',headers=headers(9002))).status_code == 200
    clock[0] = clock[0].replace(minute=50,second=0)
    opened = (await full_client.get('/flow/state',headers=headers())).json()
    assert len(opened['periods']) == 1


async def test_state_uses_one_snapshot_instead_of_reload_per_field(full_client, pgdb):
    selects=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            selects.append(statement)
    event.listen(pgdb.engine.sync_engine,'before_cursor_execute',capture)
    try:
        response = await full_client.get('/flow/state',headers=headers(9001))
        assert response.status_code == 200
        assert len(selects) <= 12, len(selects)
    finally:
        event.remove(pgdb.engine.sync_engine,'before_cursor_execute',capture)


async def test_bot_and_api_pools_compete_for_one_reservation(full_client, pgdb):
    async with pgdb.sessions() as session:
        schema = await session.scalar(text('SELECT current_schema()'))
    bot_db = Database(os.environ['TEST_DATABASE_URL'],
                      connect_args={'server_settings':{'search_path':schema}})
    try:
        bot = PostgresStore(bot_db.sessions,clock=local_now)
        await bot.register(SimpleNamespace(id=1002,first_name='Другой студент',username=None))
        state = (await full_client.get('/flow/state',headers=headers())).json()
        period = state['periods'][0]['id']
        staff = (await full_client.get('/flow/staff/1',headers=headers(9002))).json()
        await perform(full_client,'set_slots',uid=9002,cafe_id='1',break_id=period,value=1,
                      revision=staff['periods'][0]['revision'])
        web_session = (await perform(full_client,'begin'))['result']
        bot_session = await bot.call('orders','begin',1002)
        web, native = await asyncio.gather(
            full_client.post('/flow/action',headers=headers(),json={'action':'prepare','cafe_id':'1',
                'drink_id':'1_350','break_id':period,'session':web_session}),
            bot.call('orders','prepare',1002,'1','1_350',period,local_now(),session=bot_session),
            return_exceptions=True)
        assert not isinstance(web,Exception)
        assert (web.status_code==200) + isinstance(native,Draft) == 1
        assert web.status_code in (200,409)
        assert isinstance(native,(Draft,OrderError))
        uid, token = (1001,web.json()['result']['token']) if web.status_code==200 else (1002,native.token)
        api_order, bot_order = await asyncio.gather(
            perform(full_client,'confirm',uid=uid,token=token),
            bot.call('orders','confirm_once',uid,token,local_now()))
        assert api_order['result']['number'] == bot_order[0].number
        assert len(await bot.call('orders','for_user',uid)) == 1
        final = (await full_client.get('/flow/staff/1',headers=headers(9002))).json()['periods'][0]
        assert (final['free'],final['confirmed'],final['reserved']) == (0,1,0)
    finally:
        await bot_db.close()
