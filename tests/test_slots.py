import asyncio
import unittest
from datetime import timedelta
from unittest.mock import patch

from aiogram.types import User

from app import settings
from app.handlers import staff, student
from app.schedule import order_windows, available_breaks, test_break as make_test_break
from app.services.orders import OrderError, OrderService
from app.services.roles import AccessError, roles
from app.staff_keyboards import slot_breaks_keyboard, slot_limit_keyboard
from tests import test_staff as fixtures


class SlotServiceTests(fixtures.StaffSetup, unittest.TestCase):
    def setUp(self):
        self.setup_staff()
        self.pickup = make_test_break(self.now)

    def prepare(self, user_id=1, cafe_id='1', now=None):
        now = now or self.now
        return self.orders.prepare(user_id, cafe_id, '1_350' if cafe_id == '1' else '1_portion',
                                   make_test_break(now).id, now)

    def slots(self, now=None, cafe_id='1'):
        return self.orders.slots(cafe_id, self.pickup.id, now or self.now)

    def set_limit(self, value):
        return self.orders.set_slot_limit(101, '1', self.pickup.id, value, self.now)

    def test_ten_reservations_block_eleventh(self):
        for user_id in range(1, 11):
            self.prepare(user_id)
        self.assertEqual(self.slots().free, 0)
        with self.assertRaises(OrderError):
            self.prepare(11)
        self.assertEqual(self.slots().reserved, 10)
        self.assertEqual(self.slots(cafe_id='2').free, 10)

    def test_reservation_becomes_one_order_and_replay_does_not_consume_more(self):
        self.set_limit(1)
        draft = self.prepare()
        self.assertEqual((self.slots().free, self.slots().reserved), (0, 1))
        first = self.orders.confirm(1, draft.token, self.now + timedelta(seconds=60))
        again = self.orders.confirm(1, draft.token, self.now + timedelta(minutes=10))
        self.assertEqual(first, again)
        self.assertEqual((self.slots().confirmed, self.slots().reserved, self.slots().free), (1, 0, 0))

    def test_expired_reservation_releases_slot_but_cannot_be_confirmed(self):
        self.set_limit(1)
        draft = self.prepare()
        before = self.now + timedelta(seconds=settings.SLOT_RESERVATION_SECONDS - 1)
        deadline = self.now + timedelta(seconds=settings.SLOT_RESERVATION_SECONDS)
        self.assertEqual(self.slots(before).free, 0)
        self.assertEqual(self.slots(deadline).free, 1)
        replacement = self.prepare(2, now=deadline)
        with self.assertRaises(OrderError):
            self.orders.confirm(1, draft.token, deadline)
        self.orders.confirm(2, replacement.token, deadline)
        self.assertEqual(self.slots(deadline).confirmed, 1)

    def test_comment_change_does_not_extend_reservation(self):
        draft = self.prepare()
        self.orders.start_comment(1, draft.token, self.now)
        later = self.now + timedelta(seconds=60)
        edited = self.orders.save_comment(1, draft.token, 'со льдом', later)
        self.assertEqual(edited.reserved_until, draft.reserved_until)
        with self.assertRaises(OrderError):
            self.orders.confirm(1, edited.token, draft.reserved_until)

    def test_cancel_and_navigation_release_reservation(self):
        for release in [self.orders.cancel, self.orders.begin, self.orders.discard_draft]:
            self.prepare()
            self.assertEqual(self.slots().free, 9)
            release(1)
            self.assertEqual(self.slots().free, 10)

    def test_same_user_replacement_needs_only_one_slot(self):
        self.set_limit(1)
        old = self.prepare()
        new = self.prepare()
        self.assertEqual(self.slots().reserved, 1)
        with self.assertRaises(OrderError):
            self.orders.confirm(1, old.token, self.now)
        self.orders.confirm(1, new.token, self.now)

    def test_done_does_not_release_capacity_but_cancellation_does(self):
        self.set_limit(2)
        first = self.create_order()
        second = self.create_order(user_id=2)
        for status in ['preparing', 'ready', 'done']:
            first = self.orders.transition(101, first.number, status, first.revision, self.now)
        self.assertEqual(self.slots().free, 0)
        self.assertEqual((self.slots().completed, self.slots().active), (1, 1))
        self.orders.transition(101, second.number, 'cancelled', 0, self.now)
        self.assertEqual(self.slots().free, 1)
        with self.assertRaises(OrderError):
            self.orders.transition(101, second.number, 'cancelled', 0, self.now)
        self.assertEqual(self.slots().free, 1)

    def test_only_staff_can_add_slots_and_repeated_button_is_stale(self):
        self.set_limit(1)
        order = self.create_order()
        for status in ('preparing', 'ready', 'done'):
            order = self.orders.transition(101, order.number, status, order.revision, self.now)
        summary = self.slots()
        self.assertEqual((summary.free, summary.completed), (0, 1))
        for uid in (1, 201):
            with self.assertRaises(AccessError):
                self.orders.add_slots(uid, '1', self.pickup.id, 5, self.now, summary.revision)
        added = self.orders.add_slots(101, '1', self.pickup.id, 5, self.now, summary.revision)
        self.assertEqual((added.limit, added.free, added.completed), (6, 5, 1))
        with self.assertRaises(OrderError):
            self.orders.add_slots(101, '1', self.pickup.id, 5, self.now, summary.revision)
        self.assertEqual(self.slots().limit, 6)

    def test_add_slots_rejects_invalid_values_and_limit_overflow(self):
        revision = self.slots().revision
        for count in (0, -1, True, 1.5, '5', 1000):
            with self.assertRaises(OrderError):
                self.orders.add_slots(101, '1', self.pickup.id, count, self.now, revision)
        self.set_limit(999)
        with self.assertRaises(OrderError):
            self.orders.add_slots(101, '1', self.pickup.id, 1, self.now, self.slots().revision)

    def test_limit_cannot_be_lower_than_confirmed_plus_reservations(self):
        self.create_order()
        self.prepare(2)
        with self.assertRaises(OrderError):
            self.set_limit(1)
        self.set_limit(2)
        self.assertEqual(self.slots().free, 0)
        self.orders.cancel(2)
        self.set_limit(1)
        self.assertEqual(self.slots().limit, 1)

    def test_zero_invalid_values_and_permissions(self):
        self.set_limit(0)
        with self.assertRaises(OrderError):
            self.prepare()
        for value in [-1, 1000, True, 1.5, '10']:
            with self.assertRaises(OrderError):
                self.set_limit(value)
        with self.assertRaises(AccessError):
            self.orders.set_slot_limit(201, '1', self.pickup.id, 10, self.now)

    def test_other_employee_and_previous_process_cannot_use_stale_revision(self):
        original = self.slots()
        self.orders.set_slot_limit(101, '1', self.pickup.id, 5, self.now, original.revision)
        with self.assertRaises(OrderError):
            self.orders.set_slot_limit(102, '1', self.pickup.id, 15, self.now, original.revision)
        new_service = OrderService()
        with self.assertRaises(OrderError):
            new_service.set_slot_limit(101, '1', self.pickup.id, 15, self.now, original.revision)

    def test_schedule_cutoff_caps_reservation(self):
        now = self.now.replace(hour=9, minute=39, second=59)
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            pickup = available_breaks(now)[0]
            draft = self.orders.prepare(1, '1', '1_350', pickup.id, now)
            self.assertEqual(draft.reserved_until, pickup.closes_at)
            with self.assertRaises(OrderError):
                self.orders.confirm(1, draft.token, pickup.closes_at)

    def test_configure_future_break_and_independent_quotas(self):
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            first, second = order_windows(self.now.date())[:2]
            self.orders.set_slot_limit(101, '1', first.id, 1, self.now)
            self.orders.set_slot_limit(101, '1', second.id, 2, self.now)
            self.assertEqual(self.orders.slots('1', first.id, self.now).limit, 1)
            self.assertEqual(self.orders.slots('1', second.id, self.now).limit, 2)
            with self.assertRaises(OrderError):
                self.orders.prepare(1, '1', '1_350', second.id, self.now)
            with self.assertRaises(OrderError):
                self.orders.set_slot_limit(101, '1', first.id, 1, first.closes_at)

    def test_live_quota_continues_through_long_break_and_changes_after_short_pause(self):
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            first = available_breaks(self.now)[0]
            draft = self.orders.prepare(1, '1', '1_350', first.id, self.now)
            self.orders.confirm(1, draft.token, self.now)
            self.assertEqual(self.orders.slots('1', first.id, self.now).free, 9)
            after_pause = self.now.replace(hour=9, minute=50)
            second = available_breaks(after_pause)[0]
            self.assertNotEqual(first.id, second.id)
            self.assertEqual(self.orders.slots('1', second.id, after_pause).free, 10)
            during_long_break = self.now.replace(hour=10, minute=35)
            self.assertEqual(available_breaks(during_long_break)[0].id, second.id)

    def test_test_mode_capacity_and_reservation_reset_at_midnight(self):
        now = self.now.replace(hour=23, minute=59, second=59)
        pickup = make_test_break(now)
        self.orders.set_slot_limit(101, '1', pickup.id, 1, now)
        draft = self.prepare(now=now)
        tomorrow = now + timedelta(seconds=1)
        self.assertEqual(draft.reserved_until, tomorrow)
        with self.assertRaises(OrderError):
            self.orders.confirm(1, draft.token, tomorrow)
        new_pickup = make_test_break(tomorrow)
        self.assertNotEqual(new_pickup.id, pickup.id)
        self.assertEqual(self.orders.slots('1', new_pickup.id, tomorrow).free, 10)

    def test_slot_buttons_respect_telegram_limit(self):
        summary = self.slots()
        for keyboard in [slot_breaks_keyboard('1', [(self.pickup, summary)]),
                         slot_limit_keyboard('1', self.pickup, summary)]:
            for row in keyboard.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode()), 64)


class SlotFlowTests(fixtures.StaffSetup, unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.StaffFlowTests.setUp
    callback = fixtures.StaffFlowTests.callback

    async def test_menu_history_and_barista_work_during_order_pause(self):
        source = self.create_order()
        paused = self.now.replace(hour=9, minute=40)
        with patch('app.settings.FOLLOW_SCHEDULE', True), \
                patch('app.handlers.student.local_now', lambda: paused), \
                patch('app.handlers.staff.local_now', lambda: paused):
            await student.show_cafes(self.message, 1)
            self.assertIn('09:50', self.send.call_args.args[0])
            session = self.orders.session(1)
            await student.menu_callback(self.callback(1, f'cafe:1:{session}'))
            self.assertIn('Меню доступно для просмотра', self.edit.call_args.args[0])
            await student.menu_callback(self.callback(1, f'size:1:1_350:{session}'))
            self.assertIn('приостановлен', self.edit.call_args.args[0])
            self.assertNotIn(1, self.orders.drafts)
            await student.show_my_orders(self.callback(1, 'my_orders'), 1)
            self.assertIn(f'Заказ №{source.number}', self.edit.call_args.args[0])
            await staff.staff_callback(self.callback(101, f'staff_status:{source.reference}:preparing:0'))
            self.assertEqual(self.orders.get_order(source.number).status, 'preparing')

    async def test_add_slots_button_updates_quota_and_student_cannot_use_it(self):
        pickup = make_test_break(self.now)
        summary = self.orders.slots('1', pickup.id, self.now)
        keyboard = slot_limit_keyboard('1', pickup, summary)
        data = next(button.callback_data for row in keyboard.inline_keyboard for button in row
                    if button.text.startswith('+5'))
        await staff.staff_callback(self.callback(1, data))
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).limit, 10)
        await staff.staff_callback(self.callback(101, data))
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).limit, 15)
        self.assertIn('Выдано (квота потрачена)', self.edit.call_args.args[0])
        await staff.staff_callback(self.callback(101, data))
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).limit, 15)

    async def test_barista_types_limit_and_student_sees_free_slots(self):
        pickup = make_test_break(self.now)
        await staff.staff_callback(self.callback(101, f'staff_editslots:1:{pickup.id}'))
        message = self.message.model_copy(update={'from_user': User(id=101, is_bot=False, first_name='Barista'), 'text': '3'})
        await staff.slot_limit_input(message)
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).limit, 3)
        with patch('app.handlers.student.local_now', lambda: self.now):
            await student.show_cafes(message, 1)
        labels = [button.text for row in self.send.call_args.kwargs['reply_markup'].inline_keyboard for button in row]
        self.assertTrue(any('CaVa' in label and '3/3' in label for label in labels))

    async def test_last_slot_two_students_only_one_reserves(self):
        pickup = make_test_break(self.now)
        self.orders.set_slot_limit(101, '1', pickup.id, 1, self.now)
        sessions = {user_id: self.orders.begin(user_id) for user_id in [1, 2]}
        with patch('app.handlers.student.local_now', lambda: self.now):
            await asyncio.gather(*[
                student.menu_callback(self.callback(user_id, f'size:1:1_350:{session}'))
                for user_id, session in sessions.items()
            ])
        self.assertEqual(len(self.orders.drafts), 1)
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).reserved, 1)

    async def test_revoked_barista_cannot_finish_limit_input(self):
        pickup = make_test_break(self.now)
        self.orders.start_slot_edit(101, '1', pickup.id, self.now)
        roles.assign(900, 101, '1', False)
        message = self.message.model_copy(update={'from_user': User(id=101, is_bot=False, first_name='Barista'), 'text': '3'})
        await staff.slot_limit_input(message)
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).limit, 10)
        self.assertNotIn(101, self.orders.slot_edits)

    async def test_changed_limit_ends_stale_text_input(self):
        pickup = make_test_break(self.now)
        self.orders.start_slot_edit(101, '1', pickup.id, self.now)
        self.orders.set_slot_limit(102, '1', pickup.id, 20, self.now)
        message = self.message.model_copy(update={'from_user': User(id=101, is_bot=False, first_name='Barista'), 'text': '3'})
        await staff.slot_limit_input(message)
        self.assertEqual(self.orders.slots('1', pickup.id, self.now).limit, 20)
        self.assertNotIn(101, self.orders.slot_edits)
