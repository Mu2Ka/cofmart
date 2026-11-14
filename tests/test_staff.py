import unittest
import asyncio
from tests.memory_store import AsyncService, MemoryStore
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message

from app.handlers import entry, staff, student
from app.notifications import notify_staff, notify_student
from app.schedule import test_break as make_test_break, LOCAL_TIMEZONE
from app.services.cafes import CafeError, cafes
from app.services.orders import OrderError, OrderService
from app.services.roles import AccessError, roles
from app.staff_keyboards import roles_keyboard


class StaffSetup:
    def setup_staff(self):
        self.now = datetime(2026, 11, 13, 9, 20, tzinfo=LOCAL_TIMEZONE)
        for target, value in [
            ('app.settings.FOLLOW_SCHEDULE', False),
            ('app.settings.ADMIN_IDS', {900}),
            ('app.settings.BARISTA_CAFES', {101: {'1'}, 102: {'1'}, 201: {'2'}}),
            ('app.services.roles.roles.assignments', {}),
            ('app.services.cafes.cafes.paused', set()),
            ('app.services.cafes.cafes.stoplist', set()),
        ]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.orders = OrderService()
        memory = MemoryStore(self.orders)
        mocked = patch('app.services.persistent.get_store', lambda: memory)
        mocked.start()
        self.addCleanup(mocked.stop)

    def create_order(self, user_id=1, cafe_id='1'):
        sku = '1_350' if cafe_id == '1' else '1_portion'
        self.orders.begin(user_id)
        draft = self.orders.prepare(user_id, cafe_id, sku, make_test_break(self.now).id, self.now)
        self.orders.start_comment(user_id, draft.token, self.now)
        draft = self.orders.save_comment(user_id, draft.token, 'со льдом', self.now)
        return self.orders.confirm(user_id, draft.token, self.now)


class StaffServiceTests(StaffSetup, unittest.TestCase):
    def setUp(self):
        self.setup_staff()

    def test_bot_id_in_role_settings_is_reported(self):
        self.assertEqual(roles.configuration_warnings(999), [])
        self.assertTrue(roles.configuration_warnings(900))
        self.assertTrue(roles.configuration_warnings(101))

    def test_roles_grant_revoke_and_no_self_promotion(self):
        self.assertEqual(roles.cafes_for(101), {'1'})
        self.assertEqual(roles.cafes_for(900), {'1', '2'})
        with self.assertRaises(AccessError):
            roles.assign(101, 101, '2', True)
        roles.assign(900, 101, '2', True)
        self.assertEqual(roles.cafes_for(101), {'1', '2'})
        roles.assign(900, 101, '1', False)
        self.assertEqual(roles.cafes_for(101), {'2'})
        self.assertNotIn('2', roles.cafes_for(999))

    def test_full_lifecycle_and_cafe_isolation(self):
        order = self.create_order()
        self.create_order(user_id=2, cafe_id='2')
        self.assertEqual(len(self.orders.for_cafe(101, '1')), 1)
        with self.assertRaises(AccessError):
            self.orders.for_cafe(101, '2')
        with self.assertRaises(AccessError):
            self.orders.transition(201, order.number, 'preparing', 0, self.now)
        for revision, status in enumerate(['preparing', 'ready', 'done']):
            updated = self.orders.transition(101, order.number, status, revision, self.now)
            self.assertEqual(updated.status, status)
            self.assertEqual(updated.draft.comment, 'со льдом')
        self.assertEqual(self.orders.for_cafe(101, '1'), [])
        self.assertEqual(len(self.orders.for_cafe(101, '1', 'done')), 1)
        with self.assertRaises(OrderError):
            self.orders.transition(101, order.number, 'ready', 3, self.now)

    def test_two_baristas_and_stale_buttons(self):
        order = self.create_order()
        self.orders.transition(101, order.number, 'preparing', 0, self.now)
        with self.assertRaises(OrderError):
            self.orders.transition(102, order.number, 'preparing', 0, self.now)
        with self.assertRaises(OrderError):
            self.orders.transition(102, order.number, 'ready', 1, self.now)
        ready = self.orders.transition(900, order.number, 'ready', 1, self.now)
        self.assertEqual(ready.barista_id, 101)

    def test_cancellation_and_skipping_statuses(self):
        order = self.create_order()
        with self.assertRaises(OrderError):
            self.orders.transition(101, order.number, 'done', 0, self.now)
        self.orders.transition(101, order.number, 'cancelled', 0, self.now)
        with self.assertRaises(OrderError):
            self.orders.transition(101, order.number, 'preparing', 1, self.now)

    def test_pause_and_stoplist_rechecked_at_confirmation(self):
        self.orders.begin(1)
        draft = self.orders.prepare(1, '1', '1_350', make_test_break(self.now).id, self.now)
        cafes.set_open(101, '1', False)
        with self.assertRaises(OrderError):
            self.orders.confirm(1, draft.token, self.now)
        cafes.set_open(101, '1', True)
        cafes.set_available(101, '1', '1', False)
        with self.assertRaises(OrderError):
            self.orders.confirm(1, draft.token, self.now)
        cafes.set_available(101, '1', '1', True)
        self.assertEqual(self.orders.confirm(1, draft.token, self.now).status, 'new')
        with self.assertRaises(AccessError):
            cafes.set_open(101, '2', False)
        with self.assertRaises(CafeError):
            cafes.set_available(101, '1', '999', False)

    def test_role_buttons_and_revoked_permission(self):
        student_buttons = str(asyncio.run(roles_keyboard(1)))
        self.assertNotIn('role:barista', student_buttons)
        self.assertNotIn('role:admin', str(asyncio.run(roles_keyboard(101))))
        order = self.create_order()
        roles.assign(900, 101, '1', False)
        with self.assertRaises(AccessError):
            self.orders.for_staff(101, order.number)


class StaffFlowTests(StaffSetup, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_staff()
        self.edit = AsyncMock()
        self.send = AsyncMock()
        for target, value in [
            ('app.handlers.staff.orders', AsyncService(self.orders)),
            ('app.handlers.student.orders', AsyncService(self.orders)),
            ('app.handlers.entry.orders', AsyncService(self.orders)),
            ('app.handlers.staff.local_now', lambda: self.now),
            ('aiogram.types.Message.edit_text', self.edit),
            ('aiogram.types.Message.answer', self.send),
        ]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.message = Message.model_construct(message_id=1, date=self.now, chat=Chat(id=1, type='private'))
        self.bot = AsyncMock()

    def callback(self, user_id, data):
        return SimpleNamespace(from_user=SimpleNamespace(id=user_id), data=data,
                               message=self.message, answer=AsyncMock(), bot=self.bot)

    async def test_barista_status_notification_and_forged_button(self):
        order = self.create_order()
        await staff.staff_callback(self.callback(201, f'staff_order:{order.reference}'))
        self.assertIn('нет доступа', self.edit.call_args.args[0])
        await staff.staff_callback(self.callback(101, f'staff_order:{order.reference}'))
        self.assertIn('со льдом', self.edit.call_args.args[0])
        await staff.staff_callback(self.callback(101, f'staff_status:{order.reference}:preparing:0'))
        await staff.staff_callback(self.callback(101, f'staff_status:{order.reference}:ready:1'))
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertEqual(self.bot.send_message.call_args.args[0], 1)
        self.assertIn('Можно забирать', self.bot.send_message.call_args.args[1])
        await staff.staff_callback(self.callback(101, f'staff_status:{order.reference}:ready:1'))
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_student_order_privacy(self):
        order = self.create_order()
        await student.student_order(self.callback(2, f'student_order:{order.reference}'))
        self.assertNotIn('со льдом', self.edit.call_args.args[0])
        await student.student_order(self.callback(1, f'student_order:{order.reference}'))
        self.assertIn('со льдом', self.edit.call_args.args[0])

    async def test_new_order_notifies_only_assigned_staff_and_only_once(self):
        self.orders.begin(1)
        draft = self.orders.prepare(1, '1', '1_350', make_test_break(self.now).id, self.now)
        with patch('app.handlers.student.local_now', lambda: self.now):
            await student.confirm_callback(self.callback(1, f'confirm:{draft.token}'))
            await student.confirm_callback(self.callback(1, f'confirm:{draft.token}'))
        self.assertEqual({call.args[0] for call in self.bot.send_message.call_args_list}, {101, 102, 900})
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_notification_failure_keeps_order(self):
        order = self.create_order()
        self.bot.send_message.side_effect = TelegramForbiddenError(
            method=SendMessage(chat_id=1, text='test'), message='bot blocked')
        with self.assertLogs('app.notifications', level='WARNING'):
            await notify_student(self.bot, order)
        self.assertEqual(self.orders.get_order(order.number), order)

    async def test_role_entry_and_unauthorized_admin(self):
        await entry.enter_role(self.callback(1, 'role:admin'))
        self.assertIn('не назначен', self.edit.call_args.args[0])
        await entry.enter_role(self.callback(101, 'role:barista'))
        self.assertIn('Рабочая панель', self.edit.call_args.args[0])
        await entry.enter_role(self.callback(900, 'role:admin'))
        self.assertIn('Панель администратора', self.edit.call_args.args[0])
