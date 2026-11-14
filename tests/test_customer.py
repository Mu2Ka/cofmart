import asyncio
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from app.catalog import PRODUCTS
from app.customer_keyboards import favorites_keyboard, shortcut_breaks_keyboard, student_order_keyboard
from app.handlers import customer as handler
from app.notifications import notify_student
from app.schedule import available_breaks, daily_breaks, test_break as make_test_break
from app.services.cafes import cafes
from app.services.customer import CustomerError, CustomerService
from app.services.orders import OrderError
from app.services.roles import AccessError
from tests import test_staff as fixtures


class CustomerServiceTests(fixtures.StaffSetup, unittest.TestCase):
    def setUp(self):
        self.setup_staff()
        self.customer = CustomerService(self.orders)

    def done(self, user_id=1):
        order = self.create_order(user_id=user_id)
        for status in ['preparing', 'ready', 'done']:
            order = self.orders.transition(101, order.number, status, order.revision, self.now)
        return order

    def test_repeat_uses_current_price_new_slot_and_original_comment(self):
        source = self.create_order()
        with patch.dict(PRODUCTS['1']['1'].sizes, {'350': 175}):
            self.orders.begin(1)
            draft = self.customer.prepare(1, 'r', source.reference, make_test_break(self.now).id, self.now)
            self.assertEqual(draft.price, 175)
            self.assertEqual(draft.comment, 'со льдом')
            self.assertNotEqual(draft.token, source.draft.token)
            self.assertEqual(len(self.orders.confirmed), 1)
            repeated = self.orders.confirm(1, draft.token, self.now)
        self.assertEqual(source.draft.price, 165)
        self.assertEqual(repeated.draft.price, 175)

    def test_repeat_cannot_use_other_users_order(self):
        source = self.create_order()
        with self.assertRaises(OrderError):
            self.customer.selection(2, 'r', source.reference)
        with self.assertRaises(OrderError):
            self.customer.add_order(2, source.reference)

    def test_repeat_and_favorite_cannot_bypass_pause_stoplist_or_capacity(self):
        source = self.create_order()
        favorite = self.customer.add_order(1, source.reference)
        pickup = make_test_break(self.now)
        self.orders.set_slot_limit(101, '1', pickup.id, 1, self.now)
        for kind, key in [('r', source.reference), ('f', favorite.key)]:
            with self.assertRaises(OrderError):
                self.customer.prepare(1, kind, key, pickup.id, self.now)
        self.orders.set_slot_limit(101, '1', pickup.id, 3, self.now)
        cafes.set_open(101, '1', False)
        with self.assertRaises(OrderError):
            self.customer.prepare(1, 'f', favorite.key, pickup.id, self.now)
        cafes.set_open(101, '1', True)
        cafes.set_available(101, '1', '1', False)
        with self.assertRaises(OrderError):
            self.customer.prepare(1, 'r', source.reference, pickup.id, self.now)

    def test_repeat_uses_new_break_and_rejects_closed_window(self):
        source = self.create_order()
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            pickup = daily_breaks(self.now.date())[0]
            draft = self.customer.prepare(1, 'r', source.reference, pickup.id, self.now)
            self.assertEqual(draft.pickup.id, pickup.id)
            with self.assertRaises(OrderError):
                self.orders.confirm(1, draft.token, pickup.closes_at)

    def test_favorite_keeps_variant_is_deduplicated_and_private(self):
        favorite = self.customer.add(1, '1', '4_450a')
        self.assertEqual(self.customer.add(1, '1', '4_450a'), favorite)
        self.assertEqual(len(self.customer.list(1)), 1)
        self.assertEqual(self.customer.list(2), [])
        with self.assertRaises(CustomerError):
            self.customer.get(2, favorite.key)
        draft = self.customer.prepare(1, 'f', favorite.key, make_test_break(self.now).id, self.now)
        self.assertEqual(draft.drink_id, '4_450a')
        self.assertEqual(draft.price, 350)
        self.assertEqual(draft.comment, '')
        self.customer.remove(1, favorite.key)
        with self.assertRaises(CustomerError):
            self.customer.selection(1, 'f', favorite.key)

    def test_saving_draft_does_not_create_order_or_extend_reservation(self):
        self.orders.begin(1)
        draft = self.orders.prepare(1, '1', '4_350', make_test_break(self.now).id, self.now)
        self.customer.add_draft(1, draft.token, self.now + timedelta(seconds=30))
        self.assertEqual(self.orders.drafts[1].reserved_until, draft.reserved_until)
        self.assertEqual(self.orders.confirmed, {})
        with self.assertRaises(OrderError):
            self.customer.add_draft(2, draft.token, self.now)

    def test_missing_menu_variant_cannot_be_ordered_but_can_be_removed(self):
        favorite = self.customer.add(1, '1', '4_450a')
        with patch.dict(PRODUCTS['1'], {}, clear=True):
            with self.assertRaises(OrderError):
                self.customer.prepare(1, 'f', favorite.key, make_test_break(self.now).id, self.now)
            self.customer.remove(1, favorite.key)
        self.assertEqual(self.customer.list(1), [])

    def test_rating_requires_owner_issued_order_and_score_one_to_five(self):
        order = self.create_order()
        with self.assertRaises(OrderError):
            self.orders.rate(1, order.reference, 5)
        for status in ['preparing', 'ready', 'done']:
            order = self.orders.transition(101, order.number, status, order.revision, self.now)
        for actor in [2, 101, 900]:
            with self.assertRaises(OrderError):
                self.orders.rate(actor, order.reference, 5)
        for rating in [0, 6, True, 1.5, '5']:
            with self.assertRaises(OrderError):
                self.orders.rate(1, order.reference, rating)
        self.assertEqual(self.orders.rate(1, order.reference, 4).rating, 4)

    def test_changing_rating_changes_one_vote_and_preserves_workflow(self):
        order = self.done()
        self.orders.rate(1, order.reference, 2)
        updated = self.orders.rate(1, order.reference, 5)
        self.assertEqual(self.orders.rating_summary(101, '1'), (1, 5.0))
        self.assertEqual(updated.revision, order.revision)
        self.assertEqual(updated.barista_id, order.barista_id)
        self.assertEqual(updated.status, 'done')
        with self.assertRaises(AccessError):
            self.orders.rating_summary(201, '1')

    def test_customer_callback_lengths_and_pagination(self):
        order = self.done()
        favorite = self.customer.add_order(1, order.reference)
        keyboards = [student_order_keyboard(order), favorites_keyboard([favorite], 0),
                     shortcut_breaks_keyboard('r', order.reference, '12345678',
                                             [(available_breaks(self.now)[0], 9, 10)])]
        for keyboard in keyboards:
            for row in keyboard.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode()), 64)


class CustomerFlowTests(fixtures.StaffSetup, unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.StaffFlowTests.setUp
    callback = fixtures.StaffFlowTests.callback

    async def asyncSetUp(self):
        self.customer = CustomerService(self.orders)
        for target, value in [('app.handlers.customer.customer', self.customer),
                              ('app.handlers.customer.orders', self.orders),
                              ('app.handlers.customer.local_now', lambda: self.now)]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    async def click(self, user_id, data):
        callback = self.callback(user_id, data)
        await handler.customer_callback(callback)
        return callback

    async def test_repeat_last_and_favorite_open_new_confirmation(self):
        source = self.create_order()
        self.create_order(user_id=2, cafe_id='2')
        await self.click(1, 'repeat_last')
        self.assertIn('со льдом', self.edit.call_args.args[0])
        self.assertEqual(len(self.orders.confirmed), 2)
        self.assertEqual(self.orders.drafts[1].drink_id, source.draft.drink_id)
        self.orders.cancel(1)
        await self.click(1, f'favorite_add:{source.reference}')
        favorite = self.customer.list(1)[0]
        await self.click(1, f'favorite_order:{favorite.key}')
        self.assertEqual(self.orders.drafts[1].comment, '')
        self.assertEqual(len(self.orders.confirmed), 2)

    async def test_repeat_schedule_keyboard_callback_is_consumed(self):
        source = self.create_order()
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            await self.click(1, f'repeat:{source.reference}')
            self.assertIn('Выберите новую перемену', self.edit.call_args.args[0])
            keyboard = self.edit.call_args.kwargs['reply_markup']
            data = keyboard.inline_keyboard[0][0].callback_data
            self.assertTrue(data.startswith('quick:r:'))
            await self.click(1, data)
            self.assertIn('Проверьте заказ', self.edit.call_args.args[0])
            self.assertFalse(self.orders.drafts[1].pickup.is_test)

    async def test_stale_shortcut_and_foreign_favorite_are_rejected(self):
        source = self.create_order()
        favorite = self.customer.add_order(1, source.reference)
        await self.click(2, f'favorite_order:{favorite.key}')
        self.assertNotIn(2, self.orders.drafts)
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            await self.click(1, f'repeat:{source.reference}')
            data = self.edit.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
            self.orders.begin(1)
            await self.click(1, data)
            self.assertIn('устарело', self.edit.call_args.args[0])

    async def test_done_notification_has_rating_buttons_and_owner_can_rate(self):
        order = self.create_order()
        for status in ['preparing', 'ready', 'done']:
            order = self.orders.transition(101, order.number, status, order.revision, self.now)
        await notify_student(self.bot, order)
        keyboard = self.bot.send_message.call_args.kwargs['reply_markup']
        data = next(button.callback_data for row in keyboard.inline_keyboard for button in row
                    if button.callback_data.endswith(':5') and button.callback_data.startswith('rate:'))
        await self.click(1, data)
        self.assertIn('Оценка: 5/5', self.edit.call_args.args[0])
        await self.click(2, data)
        self.assertEqual(self.orders.get_order(order.number).rating, 5)

    async def test_duplicate_repeat_buttons_keep_one_reservation(self):
        source = self.create_order()
        await asyncio.gather(self.click(1, f'repeat:{source.reference}'), self.click(1, f'repeat:{source.reference}'))
        self.assertEqual(len(self.orders.drafts), 1)
        summary = self.orders.slots('1', make_test_break(self.now).id, self.now)
        self.assertEqual((summary.confirmed, summary.reserved), (1, 1))
