import unittest
from unittest.mock import patch
from datetime import date, datetime, timedelta

from app.schedule import LOCAL_TIMEZONE, available_breaks, daily_breaks
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
        for item in daily_breaks(date(2026, 11, 13)):
            with self.subTest(item=item.id):
                self.assertFalse(item.accepts_orders(item.opens_at - timedelta(seconds=1)))
                self.assertTrue(item.accepts_orders(item.opens_at))
                self.assertTrue(item.accepts_orders(item.closes_at - timedelta(microseconds=1)))
                self.assertFalse(item.accepts_orders(item.closes_at))
                self.assertFalse(item.accepts_orders(item.starts_at))

    def test_closed_before_day_during_break_and_after_day(self):
        for now in [at(8, 59), at(9, 40), at(9, 45), at(10, 35), at(17, 10), at(23)]:
            self.assertEqual(available_breaks(now), [])
        self.assertEqual(len(available_breaks(at(9, 50))), 1)


class OrderTests(unittest.TestCase):
    def setUp(self):
        mode = patch('app.settings.FOLLOW_SCHEDULE', True)
        mode.start()
        self.addCleanup(mode.stop)
        self.service = OrderService()
        self.break_id = daily_breaks(at(9).date())[0].id

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
        yesterday = daily_breaks(at(9).date() - timedelta(days=1))[0].id
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



if __name__ == '__main__':
    unittest.main()
