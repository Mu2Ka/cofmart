import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta

from app.schedule import LOCAL_TIMEZONE, available_breaks, daily_breaks, order_windows, closed_message
from app.services.orders import OrderError, OrderService


def at(hour, minute=0, second=0):
    return datetime(2026, 11, 13, hour, minute, second, tzinfo=LOCAL_TIMEZONE)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        mode = patch('app.settings.FOLLOW_SCHEDULE', True)
        mode.start()
        self.addCleanup(mode.stop)

    def test_five_pairs_and_no_break_after_last_pair(self):
        breaks = daily_breaks(date(2026, 11, 13))
        self.assertEqual([item.starts_at.strftime('%H:%M') for item in breaks],
                         ['09:45', '10:35', '11:35', '12:25', '13:25',
                          '14:15', '15:15', '16:05', '17:05'])
        self.assertEqual([(item.ends_at - item.starts_at).seconds // 60 for item in breaks],
                         [5, 15, 5, 15, 5, 15, 5, 15, 5])

    def test_every_window_boundary(self):
        for item in order_windows(date(2026, 11, 13)):
            with self.subTest(item=item.id):
                self.assertFalse(item.accepts_orders(item.opens_at - timedelta(seconds=1)))
                self.assertTrue(item.accepts_orders(item.opens_at))
                self.assertTrue(item.accepts_orders(item.closes_at - timedelta(microseconds=1)))
                self.assertFalse(item.accepts_orders(item.closes_at))
                self.assertFalse(item.accepts_orders(item.starts_at))

    def test_accepts_before_after_classes_and_through_long_breaks(self):
        for now in [at(0), at(8, 59), at(9, 39, 59), at(9, 50), at(10, 30),
                    at(10, 35), at(12, 25), at(17, 10), at(23)]:
            with self.subTest(now=now):
                self.assertEqual(len(available_breaks(now)), 1)

    def test_all_five_short_break_pauses_and_exact_boundaries(self):
        for item in daily_breaks(at(9).date()):
            if not item.id.endswith('s'):
                continue
            with self.subTest(item=item.id):
                self.assertEqual(len(available_breaks(item.closes_at - timedelta(microseconds=1))), 1)
                for now in [item.closes_at, item.starts_at, item.ends_at - timedelta(microseconds=1)]:
                    self.assertEqual(available_breaks(now), [])
                    self.assertIn(item.ends_at.strftime('%H:%M'), closed_message(now))
                self.assertEqual(len(available_breaks(item.ends_at)), 1)

    def test_evening_and_following_night_share_one_quota_window(self):
        before = available_breaks(at(23, 59, 59))[0]
        after = available_breaks(at(0) + timedelta(days=1))[0]
        self.assertEqual(before.id, after.id)
        self.assertTrue(before.is_live)
        self.assertIn('Выдача по готовности', before.label)

    def test_same_pause_in_utc(self):
        from datetime import timezone
        self.assertEqual(available_breaks(at(9, 40).astimezone(timezone.utc)), [])
        self.assertEqual(available_breaks(at(9, 50)), available_breaks(at(9, 50).astimezone(timezone.utc)))


class OrderTests(unittest.TestCase):
    def setUp(self):
        mode = patch('app.settings.FOLLOW_SCHEDULE', True)
        mode.start()
        self.addCleanup(mode.stop)
        self.service = OrderService()
        self.break_id = available_breaks(at(9))[0].id

    def prepare(self):
        return self.service.prepare(1, '1', '4_350', self.break_id, at(9, 20))

    def test_confirm_rechecks_deadline(self):
        draft = self.prepare()
        with self.assertRaises(OrderError):
            self.service.confirm(1, draft.token, at(9, 40))
        self.assertEqual(len(self.service.confirmed), 0)

    def test_repeated_confirmation_is_same_order(self):
        draft = self.service.prepare(1, '1', '4_350', self.break_id, at(9, 39))
        first = self.service.confirm(1, draft.token, at(9, 39, 59))
        second = self.service.confirm(1, draft.token, at(9, 40))
        self.assertEqual(first, second)
        self.assertEqual(len(self.service.confirmed), 1)

    def test_other_user_cannot_confirm(self):
        draft = self.prepare()
        with self.assertRaises(OrderError):
            self.service.confirm(2, draft.token, at(9, 21))

    def test_yesterday_button_and_cancelled_draft(self):
        yesterday = order_windows(at(9).date() - timedelta(days=1))[0].id
        with self.assertRaises(OrderError):
            self.service.prepare(1, '1', '4_350', yesterday, at(9, 20))
        draft = self.prepare()
        self.service.cancel(1)
        with self.assertRaises(OrderError):
            self.service.confirm(1, draft.token, at(9, 21))

    def test_new_selection_invalidates_old_confirmation(self):
        old = self.prepare()
        self.prepare()
        with self.assertRaises(OrderError):
            self.service.confirm(1, old.token, at(9, 21))

    def test_old_draft_is_invalid_next_day(self):
        draft = self.prepare()
        with self.assertRaises(OrderError):
            self.service.confirm(1, draft.token, at(9, 21) + timedelta(days=1))

    def test_unknown_product_rejected(self):
        with self.assertRaises(OrderError):
            self.service.prepare(1, '1', '99', self.break_id, at(9, 20))

    def test_cancel_and_new_order_invalidate_old_buttons(self):
        first_session = self.service.begin(1)
        self.assertTrue(self.service.valid_session(1, first_session))
        self.assertFalse(self.service.valid_session(2, first_session))
        second_session = self.service.begin(1)
        self.assertFalse(self.service.valid_session(1, first_session))
        self.assertTrue(self.service.valid_session(1, second_session))
        self.service.cancel(1)
        self.assertFalse(self.service.valid_session(1, second_session))

    def test_order_keeps_name_and_price_snapshot(self):
        from app.catalog import PRODUCTS
        draft = self.prepare()
        order = self.service.confirm(1, draft.token, at(9, 21))
        # Уже принятый заказ должен отображаться даже после удаления позиции из меню.
        with patch.dict(PRODUCTS['1'], {}, clear=True):
            repeated = self.service.confirm(1, draft.token, at(9, 30))
            self.assertEqual(repeated.draft.drink_name, order.draft.drink_name)
            self.assertEqual(repeated.draft.price, order.draft.price)

    def test_night_order_can_be_confirmed_after_midnight_in_same_quota(self):
        now = at(23, 59, 30)
        pickup = available_breaks(now)[0]
        draft = self.service.prepare(1, '1', '4_350', pickup.id, now)
        later = now + timedelta(seconds=60)
        order = self.service.confirm(1, draft.token, later)
        self.assertEqual(order.draft.pickup.id, available_breaks(later)[0].id)
        self.assertEqual(self.service.slots('1', pickup.id, later).free, 9)



if __name__ == '__main__':
    unittest.main()
