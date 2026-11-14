"""Explicit, atomic upgrade of the original main database; never runs at app startup.

python -m app.db.import_main
The original tables remain in a separate backup schema. Only the known main
revision is accepted; empty and already-restructured databases use Alembic normally.
"""
import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.config import get_settings
from app.db.session import Database
from app.db.order_store import STATE_LOCK

MAIN_REVISION = '7a1a536897d6'
TABLES = ('users', 'cafes', 'orders', 'order_drafts', 'slot_limits', 'favorites',
          'barista_overrides', 'stopped_products', 'order_sessions', 'message_deletions')


def migrate_main(connection):
    if connection.dialect.name != 'postgresql':
        raise RuntimeError('Перенос из main поддерживает только PostgreSQL.')
    connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key':STATE_LOCK})
    schema = connection.scalar(text('SELECT current_schema()'))
    backup = schema + '_main_backup'
    if len(backup.encode('utf-8')) > 63:
        raise RuntimeError('Имя схемы слишком длинное для безопасного переноса.')
    inspector = inspect(connection)
    existing = set(inspector.get_table_names(schema=schema))
    if 'alembic_version' not in existing:
        raise RuntimeError('База main не найдена. Для новой базы используйте alembic upgrade head.')
    quote = connection.dialect.identifier_preparer.quote_identifier
    revisions = list(connection.scalars(text(f'SELECT version_num FROM {quote(schema)}.alembic_version')))
    if revisions != [MAIN_REVISION]:
        raise RuntimeError('Нужна база исходной main на ревизии ' + MAIN_REVISION + '. Перенос не выполнен.')
    if set(TABLES) - existing or 'first_name' not in {col['name'] for col in inspector.get_columns('users', schema=schema)}:
        raise RuntimeError('Структура базы не соответствует main. Перенос не выполнен.')
    if backup in inspector.get_schema_names():
        raise RuntimeError('Резервная схема уже существует; проверьте предыдущий перенос вручную.')
    # PostgreSQL DDL is transactional: every rename, revision and insert rolls back on failure.
    connection.execute(text(f'CREATE SCHEMA {quote(backup)}'))
    for name in TABLES:
        connection.execute(text(f'ALTER TABLE {quote(schema)}.{quote(name)} SET SCHEMA {quote(backup)}'))
    config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
    config.attributes['connection'] = connection
    command.stamp(config, 'base', purge=True)
    command.upgrade(config, 'head')
    counts = {}
    for name in TABLES:
        columns = [column['name'] for column in inspect(connection).get_columns(name, schema=backup)]
        names = ', '.join(quote(column) for column in columns)
        destination = f'{quote(schema)}.{quote("flow_" + name)}'
        source = f'{quote(backup)}.{quote(name)}'
        connection.execute(text(f'INSERT INTO {destination} ({names}) SELECT {names} FROM {source}'))
        counts[name] = connection.scalar(text(f'SELECT count(*) FROM {destination}'))
    connection.execute(text(
        "SELECT setval(pg_get_serial_sequence(:table, 'number'), "
        'GREATEST(COALESCE((SELECT max(number) FROM flow_orders), 0), 1), '
        '(SELECT count(*) > 0 FROM flow_orders))'
    ), {'table': schema + '.flow_orders'})
    return {'backup_schema': backup, 'rows': counts}


async def main():
    database = Database(get_settings().database_url)
    try:
        async with database.engine.begin() as connection:
            result = await connection.run_sync(migrate_main)
        print('Перенос main завершён. Резервная схема:', result['backup_schema'])
        for table, count in result['rows'].items():
            print(table + ':', count)
    finally:
        await database.close()


if __name__ == '__main__':
    asyncio.run(main())
