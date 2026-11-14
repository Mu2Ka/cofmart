import unittest
from datetime import datetime
from unittest.mock import patch

from app.schedule import test_break as make_test_break, LOCAL_TIMEZONE
from app.services.orders import MAX_COMMENT_LENGTH, OrderError, OrderService


class CommentTests(unittest.TestCase):
    def setUp(self):
        mode = patch('app.settings.FOLLOW_SCHEDULE', False)
        mode.start()
        self.addCleanup(mode.stop)
        self.service = OrderService()
        self.service.begin(1)
        self.now = datetime(2026, 11, 13, 9, 20, tzinfo=LOCAL_TIMEZONE)
        self.draft = self.service.prepare(1, '1', '1_350', make_test_break(self.now).id, self.now)

    def test_comment_saved_with_order_without_changing_price(self):
        self.service.start_comment(1, self.draft.token, self.now)
        draft = self.service.save_comment(1, self.draft.token, '  со льдом  ', self.now)
        self.assertEqual(draft.comment, 'со льдом')
        self.assertEqual(draft.price, self.draft.price)
        with self.assertRaises(OrderError):
            self.service.confirm(1, self.draft.token, self.now)
        order = self.service.confirm(1, draft.token, self.now)
        self.assertEqual(order.draft.comment, 'со льдом')

    def test_optional_comment_and_skip_edit(self):
        self.service.start_comment(1, self.draft.token, self.now)
        draft = self.service.save_comment(1, self.draft.token, None, self.now)
        self.assertEqual(draft.comment, '')
        self.service.start_comment(1, draft.token, self.now)
        edited = self.service.save_comment(1, draft.token, 'без сахара', self.now)
        self.service.start_comment(1, edited.token, self.now)
        unchanged = self.service.save_comment(1, edited.token, None, self.now)
        self.assertEqual(unchanged.comment, 'без сахара')

    def test_limit_and_empty_comment_can_be_corrected(self):
        self.service.start_comment(1, self.draft.token, self.now)
        for text in ['   ', 'x' * (MAX_COMMENT_LENGTH + 1)]:
            with self.assertRaises(OrderError):
                self.service.save_comment(1, self.draft.token, text, self.now)
        draft = self.service.save_comment(1, self.draft.token, 'x' * MAX_COMMENT_LENGTH, self.now)
        self.assertEqual(len(draft.comment), MAX_COMMENT_LENGTH)

    def test_other_user_cancel_and_confirmation_while_typing(self):
        with self.assertRaises(OrderError):
            self.service.start_comment(2, self.draft.token, self.now)
        self.service.start_comment(1, self.draft.token, self.now)
        with self.assertRaises(OrderError):
            self.service.confirm(1, self.draft.token, self.now)
        self.service.begin(1)
        self.assertNotIn(1, self.service.waiting_comments)
        with self.assertRaises(OrderError):
            self.service.save_comment(1, self.draft.token, 'со льдом', self.now)

    def test_comment_does_not_bypass_deadline(self):
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            draft = self.service.prepare(1, '1', '1_350', '20261113-1s', self.now)
            self.service.start_comment(1, draft.token, self.now)
            cutoff = self.now.replace(hour=9, minute=40)
            with self.assertRaises(OrderError):
                self.service.save_comment(1, draft.token, 'со льдом', cutoff)
            self.assertNotIn(1, self.service.waiting_comments)
