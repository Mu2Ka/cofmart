"""Upgrade the real main schema, including all persisted business state, in isolation."""
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.autogenerate import compare_metadata
from sqlalchemy import inspect, text

from app.db.import_main import MAIN_REVISION, TABLES, migrate_main
from app.db.models import Base
from app.db.order_store import PostgresStore, pack_draft
from app.db.session import Database
from app.db.readiness import ensure_schema
from app.ordering import settings
from app.ordering.orders import OrderService
from app.ordering.schedule import LOCAL_TIMEZONE, test_break as make_test_break

pytestmark = pytest.mark.postgres


def config(connection):
    result = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
    result.attributes['connection'] = connection
    return result


@pytest.fixture
async def main_db(monkeypatch):
    url = os.getenv('TEST_DATABASE_URL', '')
    if not url.startswith('postgresql+asyncpg://'):
        pytest.skip('Set TEST_DATABASE_URL')
    schema = 'main_test_' + uuid4().hex
    control = Database(url)
    async with control.engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    db = Database(url, connect_args={'server_settings': {'search_path': schema}})
    try:
        def original_schema(connection):
            folder = Path(__file__).resolve().parents[1] / 'fixtures' / 'main_migrations'
            with Operations.context(MigrationContext.configure(connection)):
                for prefix in ('c3188f', 'e0ae7a', '7a1a53'):
                    path = next(folder.glob(prefix + '*.py'))
                    spec = importlib.util.spec_from_file_location('original_' + prefix, path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    module.upgrade()
            connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
            connection.execute(text('INSERT INTO alembic_version VALUES (:revision)'), {'revision': MAIN_REVISION})
        async with db.engine.begin() as conn:
            await conn.run_sync(original_schema)
        monkeypatch.setattr(settings, 'FOLLOW_SCHEDULE', False)
        now = datetime(2031, 1, 2, 9, 20, tzinfo=LOCAL_TIMEZONE)
        rules = OrderService()
        draft = rules.prepare(1001, '1', '1_350', make_test_break(now).id, now, comment='со льдом <много>')
        pending = rules.prepare(1001, '2', '1_portion', make_test_break(now).id, now)
        async with db.engine.begin() as conn:
            await conn.execute(text("INSERT INTO users(id,first_name) VALUES (1001,'Студент')"))
            await conn.execute(text("INSERT INTO cafes(id,name,accepts_orders) VALUES ('1','CaVa',false),('2','Порт-Брю',true)"))
            values = {'token': draft.token, 'draft': json.dumps(pack_draft(draft)), 'bid': draft.pickup.id, 'now': now}
            await conn.execute(text("INSERT INTO orders(number,token,key,user_id,cafe_id,break_id,draft,status,revision,barista_id,rating,created_at,updated_at) "
                                    "VALUES (42,:token,'0123456789abcdef',1001,'1',:bid,CAST(:draft AS JSONB),'done',3,9002,5,:now,:now)"), values)
            await conn.execute(text("INSERT INTO order_drafts(user_id,token,cafe_id,break_id,reserved_until,draft) "
                                    "VALUES (1001,:token,'2',:bid,:until,CAST(:draft AS JSONB))"),
                               {'token': pending.token, 'bid': pending.pickup.id, 'until': pending.reserved_until,
                                'draft': json.dumps(pack_draft(pending))})
            await conn.execute(text('INSERT INTO slot_limits VALUES (:cid,:bid,:limit,:rev)'),
                               {'cid':'1','bid':draft.pickup.id,'limit':6,'rev':12})
            await conn.execute(text("INSERT INTO favorites VALUES ('123456abcdef',1001,'1','1_350','CaVa','Американо')"))
            await conn.execute(text("INSERT INTO barista_overrides VALUES (9002,ARRAY['1'])"))
            await conn.execute(text("INSERT INTO stopped_products VALUES ('1','4')"))
            await conn.execute(text("INSERT INTO order_sessions(user_id,token,waiting_comment) VALUES (1001,'12345678',:token)"), {'token':pending.token})
            await conn.execute(text('INSERT INTO message_deletions VALUES (123456,1001,8,:now)'), {'now':now})
        yield db, schema, now
    finally:
        await db.close()
        async with control.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}_main_backup" CASCADE'))
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await control.close()


async def test_main_upgrade_preserves_all_tables_and_original_backup(main_db):
    db, schema, now = main_db
    with pytest.raises(RuntimeError,match='app.db.import_main'):
        await ensure_schema(db)
    async with db.engine.begin() as conn:
        result = await conn.run_sync(migrate_main)
    await ensure_schema(db)
    assert result['rows'] == {name: (2 if name == 'cafes' else 1) for name in TABLES}
    async with db.engine.connect() as conn:
        assert await conn.scalar(text('SELECT version_num FROM alembic_version')) == '48bbf2db8a9b'
        assert await conn.scalar(text(f'SELECT count(*) FROM "{schema}_main_backup".orders')) == 1
        assert await conn.scalar(text("SELECT nextval(pg_get_serial_sequence('flow_orders','number'))")) == 43
        differences = await conn.run_sync(lambda sync: compare_metadata(
            MigrationContext.configure(sync, opts={'compare_type':True,'compare_server_default':True}), Base.metadata))
        assert differences == []
    store = PostgresStore(db.sessions)
    order = (await store.call('orders','for_user',1001))[0]
    assert (order.number,order.status,order.rating,order.draft.comment) == (42,'done',5,'со льдом <много>')
    assert (await store.call('roles','cafes_for',9002)) == {'1'}
    assert not await store.call('cafes','is_open','1')
    assert len(await store.call('customer','list',1001)) == 1
    assert (await store.call('orders','slots','1',order.draft.pickup.id,now)).free == 5


async def test_failed_import_rolls_back_ddl_and_revision(main_db, monkeypatch):
    db, schema, _ = main_db
    def fail(*args, **kwargs):
        raise RuntimeError('injected migration failure')
    monkeypatch.setattr('app.db.import_main.command.upgrade', fail)
    with pytest.raises(RuntimeError, match='injected'):
        async with db.engine.begin() as conn:
            await conn.run_sync(migrate_main)
    async with db.engine.connect() as conn:
        assert await conn.scalar(text('SELECT version_num FROM alembic_version')) == MAIN_REVISION
        assert await conn.scalar(text('SELECT count(*) FROM orders')) == 1
        assert not await conn.run_sync(lambda sync: inspect(sync).has_schema(schema + '_main_backup'))


async def test_import_refuses_unknown_revision_without_mutation(main_db):
    db, schema, _ = main_db
    async with db.engine.begin() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num='unknown'"))
    with pytest.raises(RuntimeError, match='Нужна база'):
        async with db.engine.begin() as conn:
            await conn.run_sync(migrate_main)
    async with db.engine.connect() as conn:
        assert await conn.scalar(text('SELECT count(*) FROM orders')) == 1
        assert not await conn.run_sync(lambda sync: inspect(sync).has_schema(schema + '_main_backup'))


async def test_import_refuses_repeat_without_overwriting_existing_data(main_db):
    db, schema, _ = main_db
    async with db.engine.begin() as conn:
        await conn.run_sync(migrate_main)
    with pytest.raises(RuntimeError,match='Нужна база'):
        async with db.engine.begin() as conn:
            await conn.run_sync(migrate_main)
    async with db.engine.connect() as conn:
        assert await conn.scalar(text('SELECT count(*) FROM flow_orders')) == 1
        assert await conn.scalar(text(f'SELECT count(*) FROM "{schema}_main_backup".orders')) == 1
