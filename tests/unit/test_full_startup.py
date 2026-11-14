from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.methods import SetMyCommands

from app.bot import main
from app.ordering import settings
from tests.helpers import TOKEN


@pytest.fixture
def runtime(monkeypatch):
    bot = AsyncMock()
    bot.id = 123456
    bot.__aenter__.return_value = bot
    bot.__aexit__.return_value = False
    dispatcher = MagicMock()
    dispatcher.start_polling = AsyncMock()
    dispatcher.storage.close = AsyncMock()
    dispatcher.fsm.events_isolation.close = AsyncMock()
    ensure, close = AsyncMock(), AsyncMock()
    factory = MagicMock(return_value=bot)

    @asynccontextmanager
    async def worker(bot):
        yield

    monkeypatch.setattr(main, 'Bot', factory)
    monkeypatch.setattr(main, 'Dispatcher', lambda **kwargs: dispatcher)
    monkeypatch.setattr('app.bot.message_cleanup.message_cleanup_worker', worker)
    monkeypatch.setattr('app.db.readiness.ensure_schema', ensure)
    monkeypatch.setattr('app.ordering.seed.seed', AsyncMock())
    monkeypatch.setattr('app.db.ordering_connection.database', MagicMock())
    monkeypatch.setattr('app.db.ordering_connection.close', close)
    monkeypatch.setattr(settings, 'ADMIN_IDS', set())
    monkeypatch.setattr(settings, 'BARISTA_CAFES', {})
    return bot, dispatcher, ensure, close, factory


async def test_schema_error_prevents_telegram_and_closes_db(runtime):
    bot, dispatcher, ensure, close, factory = runtime
    ensure.side_effect = RuntimeError('schema is not ready')
    with pytest.raises(RuntimeError, match='schema'):
        await main.run_bot(TOKEN)
    factory.assert_not_called()
    dispatcher.start_polling.assert_not_awaited()
    close.assert_awaited_once()


async def test_transient_command_failure_still_starts_polling(runtime):
    bot, dispatcher, ensure, close, _ = runtime
    bot.set_my_commands.side_effect = TelegramNetworkError(method=SetMyCommands(commands=[]), message='offline')
    await main.run_bot(TOKEN)
    ensure.assert_awaited_once()
    dispatcher.start_polling.assert_awaited_once_with(bot, close_bot_session=False)
    bot.__aexit__.assert_awaited_once()
    close.assert_awaited_once()


async def test_invalid_token_is_not_swallowed(runtime):
    bot, dispatcher, _, close, _ = runtime
    bot.set_my_commands.side_effect = TelegramUnauthorizedError(method=SetMyCommands(commands=[]), message='unauthorized')
    with pytest.raises(TelegramUnauthorizedError):
        await main.run_bot(TOKEN)
    dispatcher.start_polling.assert_not_awaited()
    close.assert_awaited_once()


async def test_polling_error_closes_all_resources(runtime):
    bot, dispatcher, _, close, _ = runtime
    dispatcher.start_polling.side_effect = RuntimeError('poll failed')
    with pytest.raises(RuntimeError, match='poll failed'):
        await main.run_bot(TOKEN)
    dispatcher.storage.close.assert_awaited_once()
    dispatcher.fsm.events_isolation.close.assert_awaited_once()
    bot.__aexit__.assert_awaited_once()
    close.assert_awaited_once()
