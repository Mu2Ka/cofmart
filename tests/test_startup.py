import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError
from aiogram.methods import SetMyCommands

import main


class StartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = AsyncMock()
        self.bot.id = 123456
        self.bot.__aenter__.return_value = self.bot
        self.bot.__aexit__.return_value = False
        self.dispatcher = MagicMock()
        self.dispatcher.start_polling = AsyncMock()
        self.factory = MagicMock(return_value=self.bot)
        self.cleanup = MagicMock(return_value=AsyncMock())
        for target, value in [
            ('main.prepare_database', AsyncMock()), ('main.close_database', AsyncMock()),
            ('main.message_cleanup_worker', self.cleanup),
            ('main.Bot', self.factory), ('main.Dispatcher', MagicMock(return_value=self.dispatcher)),
            ('main.get_bot_token', lambda: 'local-test-token'),
            ('app.settings.FOLLOW_SCHEDULE', False), ('app.settings.ADMIN_IDS', set()),
            ('app.settings.BARISTA_CAFES', {}),
        ]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    async def test_command_menu_network_failure_does_not_stop_polling(self):
        self.bot.set_my_commands.side_effect = TelegramNetworkError(
            method=SetMyCommands(commands=[]), message='temporary network failure')
        with self.assertLogs(level='WARNING'):
            await main.main()
        self.dispatcher.start_polling.assert_awaited_once_with(self.bot, close_bot_session=False)
        self.bot.__aexit__.assert_awaited_once()

    async def test_invalid_credentials_fail_and_close_session(self):
        self.bot.set_my_commands.side_effect = TelegramUnauthorizedError(
            method=SetMyCommands(commands=[]), message='unauthorized')
        with self.assertRaises(TelegramUnauthorizedError):
            await main.main()
        self.dispatcher.start_polling.assert_not_awaited()
        self.bot.__aexit__.assert_awaited_once()

    async def test_polling_failure_closes_session(self):
        self.dispatcher.start_polling.side_effect = RuntimeError('polling failed')
        with self.assertRaises(RuntimeError):
            await main.main()
        self.bot.__aexit__.assert_awaited_once()

    async def test_invalid_settings_fail_before_starting_bot(self):
        with patch('app.settings.ADMIN_IDS', {'123'}), self.assertRaises(ValueError):
            await main.main()
        self.factory.assert_not_called()

    async def test_database_failure_stops_startup_before_telegram(self):
        with patch('main.prepare_database', AsyncMock(side_effect=RuntimeError('schema is outdated'))):
            with self.assertRaisesRegex(RuntimeError, 'schema is outdated'):
                await main.main()
        self.factory.assert_not_called()
        main.close_database.assert_awaited_once()
