"""Adversarial interleavings of real clients, not tests of implementation details."""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql import insert

from app.db.order_store import PostgresStore, STATE_LOCK
from app.db.ordering_models import RoleOverrideRecord
from app.ordering import settings
from app.ordering.schedule import LOCAL_TIMEZONE, local_now
from tests.integration.test_full_workflow import full_client, headers, perform
from tests.integration.test_postgres import pgdb

pytestmark = pytest.mark.postgres


async def draft(client):
    state = (await client.get('/flow/state',headers=headers())).json()
    session = (await perform(client,'begin'))['result']
    value = (await perform(client,'prepare',cafe_id='1',drink_id='1_350',
        break_id=state['periods'][0]['id'],session=session))['result']
    return session, value


async def test_stale_window_cannot_cancel_comment_edited_in_second_client(full_client):
    session, old = await draft(full_client)
    current = (await perform(full_client,'comment',token=old['token'],comment='со льдом'))['result']
    await perform(full_client,'cancel',session=session,token=old['token'],expected=409)
    state = (await full_client.get('/flow/state',headers=headers())).json()
    assert state['draft']['token'] == current['token']
    assert state['draft']['comment'] == 'со льдом'
    await perform(full_client,'cancel',session=session,token=current['token'])


async def test_new_session_wins_over_old_client_messages(full_client):
    first_session, first = await draft(full_client)
    second_session, second = await draft(full_client)
    await perform(full_client,'comment',token=first['token'],comment='устарело',expected=409)
    await perform(full_client,'confirm',token=first['token'],expected=409)
    await perform(full_client,'cancel',session=first_session,token=first['token'],expected=409)
    state = (await full_client.get('/flow/state',headers=headers())).json()
    assert state['session'] == second_session
    assert state['draft']['token'] == second['token']
    assert state['cafes'][0]['slots']['reserved'] == 1


def waiting_for_lock(database):
    waiting = asyncio.Event()
    def capture(conn,cursor,statement,parameters,context,executemany):
        if 'pg_advisory_xact_lock' in statement:
            waiting.set()
    event.listen(database.engine.sync_engine,'before_cursor_execute',capture)
    return waiting, capture


async def test_cutoff_arrives_while_confirmation_is_waiting_in_postgres(full_client,pgdb,monkeypatch):
    monkeypatch.setattr(settings,'FOLLOW_SCHEDULE',True)
    clock = [datetime(2031,1,2,9,39,59,tzinfo=LOCAL_TIMEZONE)]
    monkeypatch.setattr('app.api.routers.flow.local_now',lambda:clock[0])
    _, order = await draft(full_client)
    task = None
    async with pgdb.sessions.begin() as blocker:
        await blocker.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':STATE_LOCK})
        waiting,capture = waiting_for_lock(pgdb)
        try:
            task = asyncio.create_task(full_client.post('/flow/action',headers=headers(),
                json={'action':'confirm','token':order['token']}))
            await asyncio.wait_for(waiting.wait(),timeout=3)
            clock[0] = clock[0].replace(minute=40,second=0)
        finally:
            event.remove(pgdb.engine.sync_engine,'before_cursor_execute',capture)
    response = await asyncio.wait_for(task,timeout=5)
    assert response.status_code == 409
    state = (await full_client.get('/flow/state',headers=headers())).json()
    assert state['orders'] == [] and state['draft'] is None


async def test_revocation_during_wait_is_checked_at_mutation(full_client,pgdb):
    _, pending = await draft(full_client)
    order = (await perform(full_client,'confirm',token=pending['token']))['result']
    task = None
    async with pgdb.sessions.begin() as blocker:
        await blocker.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':STATE_LOCK})
        waiting,capture = waiting_for_lock(pgdb)
        try:
            task = asyncio.create_task(full_client.post('/flow/action',headers=headers(9002),json={
                'action':'transition','reference':order['reference'],'status':'preparing','revision':0}))
            await asyncio.wait_for(waiting.wait(),timeout=3)
            statement = insert(RoleOverrideRecord).values(user_id=9002,cafe_ids=[])
            await blocker.execute(statement.on_conflict_do_update(index_elements=['user_id'],set_={'cafe_ids':[]}))
        finally:
            event.remove(pgdb.engine.sync_engine,'before_cursor_execute',capture)
    assert (await asyncio.wait_for(task,timeout=5)).status_code == 403
    state = (await full_client.get('/flow/state',headers=headers())).json()
    assert state['orders'][0]['status'] == 'new'


async def test_cancelled_waiter_does_not_leave_ghost_reservation(full_client,pgdb):
    state = (await full_client.get('/flow/state',headers=headers())).json()
    session = (await perform(full_client,'begin'))['result']
    store = PostgresStore(pgdb.sessions,clock=local_now)
    async with pgdb.sessions.begin() as blocker:
        await blocker.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':STATE_LOCK})
        waiting,capture = waiting_for_lock(pgdb)
        task = asyncio.create_task(store.call('orders','prepare',1001,'1','1_350',
            state['periods'][0]['id'],local_now(),session=session))
        try:
            await asyncio.wait_for(waiting.wait(),timeout=3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            event.remove(pgdb.engine.sync_engine,'before_cursor_execute',capture)
    restored = (await full_client.get('/flow/state',headers=headers())).json()
    assert restored['draft'] is None
    assert restored['cafes'][0]['slots']['free'] == 10
    await perform(full_client,'prepare',cafe_id='1',drink_id='1_350',break_id=state['periods'][0]['id'],session=session)
