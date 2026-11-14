"""Регрессии, найденные при полном проходе по коду."""

import asyncio
import unittest
from datetime import timezone
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import Chat, Message

from app.handlers import student, staff
from app.schedule import test_break as make_test_break, available_breaks, closed_message
from app.services.cafes import cafes
from app.services.orders import OrderError, OrderService, TRANSITIONS
from app.services.roles import AccessError, roles
from app.staff_keyboards import staff_order_keyboard, queue_keyboard, availability_keyboard
from app.ui import order_text
from tests.test_staff import StaffSetup


class AuditServiceTests(StaffSetup, unittest.TestCase):
    def setUp(self):
        self.setup_staff()

    def test_old_order_reference_cannot_target_new_order_after_restart(self):
        old = self.create_order()
        self.orders = OrderService()
        new = self.create_order(user_id=2)
        self.assertEqual(old.number, new.number)
        self.assertNotEqual(old.reference, new.reference)
        with self.assertRaises(OrderError):
            self.orders.resolve_reference(old.reference)
        self.assertEqual(self.orders.resolve_reference(new.reference), new)
        for reference in ['', '1', '1-', 'x-key', '999-key']:
            with self.subTest(reference=reference), self.assertRaises(OrderError):
                self.orders.resolve_reference(reference)

    @patch('app.settings.DEFAULT_SLOTS_PER_BREAK', 999)
    def test_all_status_transitions_for_each_role(self):
        paths = {'new': [], 'preparing': ['preparing'], 'ready': ['preparing', 'ready'],
                 'done': ['preparing', 'ready', 'done'], 'cancelled': ['cancelled']}
        for status, path in paths.items():
            for target in TRANSITIONS:
                for actor in [101, 102, 201, 900, 1]:
                    with self.subTest(status=status, target=target, actor=actor):
                        order = self.create_order()
                        for step in path:
                            order = self.orders.transition(101, order.number, step, order.revision, self.now)
                        can_change = (actor in {101, 900} or (actor == 102 and status == 'new'))
                        expected = target in TRANSITIONS[status] and can_change
                        if expected:
                            changed = self.orders.transition(actor, order.number, target, order.revision, self.now)
                            self.assertEqual(changed.status, target)
                        else:
                            with self.assertRaises((AccessError, OrderError)):
                                self.orders.transition(actor, order.number, target, order.revision, self.now)
                            self.assertEqual(self.orders.get_order(order.number), order)

    def test_pause_does_not_prevent_servicing_existing_orders(self):
        order = self.create_order()
        cafes.set_open(101, '1', False)
        cafes.set_available(101, '1', '1', False)
        for status in ['preparing', 'ready', 'done']:
            order = self.orders.transition(101, order.number, status, order.revision, self.now)
        self.assertEqual(order.status, 'done')

    def test_stoplist_covers_all_sizes_and_milk(self):
        cafes.set_available(101, '1', '4', False)
        for size in ['250', '350', '450']:
            for milk in ['', 'a']:
                with self.assertRaises(OrderError):
                    self.orders.prepare(1, '1', f'4_{size}{milk}', make_test_break(self.now).id, self.now)

    def test_settings_types_have_clear_errors(self):
        roles.validate_configuration()
        for name, value in [
            ('FOLLOW_SCHEDULE', 'False'), ('ADMIN_IDS', {True}), ('ADMIN_IDS', {'900'}),
            ('ADMIN_IDS', {}), ('BARISTA_CAFES', []), ('BARISTA_CAFES', {'101': {'1'}}),
            ('BARISTA_CAFES', {101: {1}}), ('BARISTA_CAFES', {101: {'unknown'}}),
        ]:
            with self.subTest(setting=name, value=value), patch(f'app.settings.{name}', value):
                with self.assertRaises(ValueError):
                    roles.validate_configuration()

    def test_equivalent_utc_time_has_same_schedule(self):
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            utc = self.now.astimezone(timezone.utc)
            self.assertEqual(available_breaks(self.now), available_breaks(utc))
            late = self.now.replace(hour=23, minute=59)
            self.assertIn('14.11 в 09:00', closed_message(late))

    def test_staff_callbacks_fit_telegram_limit_with_unique_order_keys(self):
        order = self.create_order()
        keyboards = [staff_order_keyboard(order, 101), queue_keyboard('1', 'active', 0, [order]),
                     availability_keyboard('1', 0)]
        for keyboard in keyboards:
            for row in keyboard.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode()), 64)

    def test_five_maximum_comments_fit_history_message(self):
        class TextParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = ''
            def handle_data(self, data):
                self.text += data
        for _ in range(5):
            draft = self.orders.prepare(1, '1', '15_450a', make_test_break(self.now).id, self.now)
            self.orders.start_comment(1, draft.token, self.now)
            draft = self.orders.save_comment(1, draft.token, '🧊' * 300, self.now)
            self.orders.confirm(1, draft.token, self.now)
        parser = TextParser()
        parser.feed('<b>📋 Мои последние заказы</b>\n\n' + '\n\n'.join(map(order_text, self.orders.for_user(1))))
        self.assertLessEqual(len(parser.text.encode('utf-16-le')) // 2, 4096)


class AuditFlowTests(StaffSetup, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.setup_staff()
        self.edit, self.send, self.bot = AsyncMock(), AsyncMock(), AsyncMock()
        for target, value in [
            ('app.handlers.student.orders', self.orders), ('app.handlers.staff.orders', self.orders),
            ('app.handlers.student.local_now', lambda: self.now),
            ('app.handlers.staff.local_now', lambda: self.now),
            ('aiogram.types.Message.edit_text', self.edit), ('aiogram.types.Message.answer', self.send),
        ]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.message = Message.model_construct(message_id=1, date=self.now, chat=Chat(id=1, type='private'))

    def callback(self, user_id, data):
        return SimpleNamespace(from_user=SimpleNamespace(id=user_id), data=data, message=self.message,
                               answer=AsyncMock(), bot=self.bot)

    async def test_navigation_cancels_old_draft_and_pending_comment(self):
        session = self.orders.begin(1)
        draft = self.orders.prepare(1, '1', '1_350', make_test_break(self.now).id, self.now)
        self.orders.start_comment(1, draft.token, self.now)
        await student.menu_callback(self.callback(1, f'product:1:4:{session}'))
        self.assertNotIn(1, self.orders.waiting_comments)
        await student.confirm_callback(self.callback(1, f'confirm:{draft.token}'))
        self.assertEqual(self.orders.confirmed, {})
        self.bot.send_message.assert_not_awaited()

    async def test_failed_customer_card_does_not_skip_barista_notification(self):
        self.orders.begin(1)
        draft = self.orders.prepare(1, '1', '1_350', make_test_break(self.now).id, self.now)
        self.edit.side_effect = TelegramBadRequest(
            method=EditMessageText(text='x'), message='Bad Request: message to edit not found')
        await student.confirm_callback(self.callback(1, f'confirm:{draft.token}'))
        self.assertEqual(self.bot.send_message.await_count, 3)
        self.assertEqual(len(self.orders.confirmed), 1)
        self.send.assert_awaited_once()
        self.edit.side_effect = None
        await student.confirm_callback(self.callback(1, f'confirm:{draft.token}'))
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_unknown_ui_error_is_not_silenced_but_order_is_not_lost(self):
        self.orders.begin(1)
        draft = self.orders.prepare(1, '1', '1_350', make_test_break(self.now).id, self.now)
        self.edit.side_effect = TelegramBadRequest(method=EditMessageText(text='x'), message='unexpected error')
        with self.assertRaises(TelegramBadRequest):
            await student.confirm_callback(self.callback(1, f'confirm:{draft.token}'))
        self.assertEqual(len(self.orders.confirmed), 1)
        self.assertEqual(self.bot.send_message.await_count, 3)

    async def test_two_concurrent_claims_only_one_wins(self):
        order = self.create_order()
        await asyncio.gather(*[
            staff.staff_callback(self.callback(user_id, f'staff_status:{order.reference}:preparing:0'))
            for user_id in [101, 102]
        ])
        updated = self.orders.get_order(order.number)
        self.assertEqual(updated.status, 'preparing')
        self.assertEqual(updated.revision, 1)
        self.assertIn(updated.barista_id, {101, 102})
        self.bot.send_message.assert_awaited_once()

    async def test_old_staff_button_cannot_change_reused_number(self):
        old = self.create_order()
        self.orders = OrderService()
        new = self.create_order(user_id=2)
        with patch('app.handlers.staff.orders', self.orders):
            await staff.staff_callback(self.callback(101, f'staff_status:{old.reference}:preparing:0'))
        self.assertEqual(self.orders.get_order(new.number).status, 'new')
        self.bot.send_message.assert_not_awaited()
        self.assertIn('устарела', self.edit.call_args.args[0])
