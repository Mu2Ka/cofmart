import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiogram.types import CallbackQuery, Chat, Message, User

from app.middlewares import BanMiddleware
from app.notifications import send
from app.services.bans import BLOCK_MESSAGE, BanService
from app.services.roles import AccessError, roles


class BanSetup:
    def setup_bans(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'blocked.json'
        self.bans = BanService(self.path)
        for target, value in [
            ('app.settings.BLOCKED_USERNAMES', {'blocked_sample_one', 'blocked_sample_two'}),
            ('app.settings.BLOCKED_USER_IDS', set()),
        ]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)


class BanServiceTests(BanSetup, unittest.TestCase):
    def setUp(self):
        self.setup_bans()

    def test_both_usernames_case_insensitive_and_id_survives_restart(self):
        for user_id, name in [(1, 'BLOCKED_SAMPLE_ONE'), (2, '@Blocked_Sample_Two')]:
            self.assertTrue(self.bans.is_blocked(user_id, name))
        restored = BanService(self.path)
        self.assertTrue(restored.is_blocked(1, 'new_username'))
        self.assertTrue(restored.is_blocked(2, None))
        self.assertEqual(json.loads(self.path.read_text()), [1, 2])

    def test_other_accounts_are_not_blocked_by_substring(self):
        for name in [None, 'blocked_sample_one2', 'a_blocked_sample_one', 'Blocked_Sample_Two7', 'student']:
            self.assertFalse(self.bans.is_blocked(99, name))
        self.assertFalse(self.path.exists())

    def test_explicit_id_does_not_require_username(self):
        with patch('app.settings.BLOCKED_USER_IDS', {123}):
            self.assertTrue(self.bans.is_blocked(123))

    def test_disk_error_still_blocks_in_current_process(self):
        with patch.object(Path, 'write_text', side_effect=OSError('read only')):
            with self.assertLogs('app.services.bans', level='ERROR'):
                self.assertTrue(self.bans.is_blocked(1, 'blocked_sample_one'))
        self.assertTrue(self.bans.is_blocked(1, 'renamed'))

    def test_corrupt_persisted_ids_fail_clearly(self):
        self.path.write_text('["123"]')
        with self.assertRaises(ValueError):
            self.bans.validate_configuration()

    def test_ban_overrides_privileged_roles(self):
        self.bans.is_blocked(900, 'blocked_sample_one')
        with patch('app.services.roles.bans', self.bans), patch('app.settings.ADMIN_IDS', {900}), \
                patch('app.settings.BARISTA_CAFES', {900: {'1'}}):
            self.assertFalse(roles.is_admin(900))
            self.assertEqual(roles.cafes_for(900), set())
            with self.assertRaises(AccessError):
                roles.require_cafe(900, '1')


class BanMiddlewareTests(BanSetup, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_bans()
        self.handler = AsyncMock(return_value='allowed')
        self.middleware = BanMiddleware(self.bans)

    async def test_blocked_start_receives_exact_message_and_no_handler(self):
        message = Message.model_construct(
            message_id=1, chat=Chat(id=1, type='private'), text='/start',
            from_user=User(id=1, first_name='Test', is_bot=False, username='blocked_sample_one'))
        with patch.object(Message, 'answer', AsyncMock()) as answer:
            await self.middleware(self.handler, message, {})
        answer.assert_awaited_once_with(BLOCK_MESSAGE)
        self.handler.assert_not_awaited()

    async def test_callback_checks_person_not_bot_who_sent_message(self):
        message = Message.model_construct(message_id=1, chat=Chat(id=1, type='private'),
                                          from_user=User(id=99, first_name='Bot', is_bot=True))
        query = CallbackQuery.model_construct(id='test', chat_instance='test', data='role:admin',
            message=message, from_user=User(id=1, first_name='Test', is_bot=False, username='BLOCKED_SAMPLE_TWO'))
        with patch.object(CallbackQuery, 'answer', AsyncMock()) as answer:
            await self.middleware(self.handler, query, {})
        answer.assert_awaited_once_with(BLOCK_MESSAGE, show_alert=True)
        self.handler.assert_not_awaited()

    async def test_allowed_account_passes_through(self):
        message = Message.model_construct(message_id=1, chat=Chat(id=1, type='private'),
            from_user=User(id=1, first_name='Test', is_bot=False))
        self.assertEqual(await self.middleware(self.handler, message, {}), 'allowed')
        self.handler.assert_awaited_once_with(message, {})

    async def test_blocked_account_does_not_receive_order_notifications(self):
        self.bans.is_blocked(1, 'blocked_sample_one')
        bot = AsyncMock()
        with patch('app.notifications.bans', self.bans):
            await send(bot, 1, 'private order', 'student_order:1', 'Открыть')
        bot.send_message.assert_not_awaited()
