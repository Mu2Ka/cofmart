import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.catalog import PRODUCTS, get_drink
from app.schedule import test_break as make_test_break, LOCAL_TIMEZONE, available_breaks, daily_breaks, find_break
from app.services.orders import OrderError, OrderService


class CatalogTests(unittest.TestCase):
    def test_every_volume_and_milk_price_is_available(self):
        for cafe_id, products in PRODUCTS.items():
            for product_id, product in products.items():
                for size, price in product.sizes.items():
                    sku = f'{product_id}_{size}'
                    self.assertEqual(get_drink(cafe_id, sku).price, price)
                    if product.alternative_milk:
                        self.assertEqual(get_drink(cafe_id, sku + 'a').price, price + 70)

    def test_photo_prices_and_existing_second_cafe(self):
        self.assertEqual(PRODUCTS['1']['4'].sizes, {'250': 240, '350': 260, '450': 280})
        self.assertEqual(PRODUCTS['1']['18'].sizes, {'350': 285, '450': 360})
        self.assertEqual(PRODUCTS['1']['38'].sizes, {'portion': 285})
        self.assertEqual(get_drink('2', '1_portion').price, 100)
        self.assertEqual(get_drink('2', '2_portion').price, 250)


    def test_invalid_size_cafe_and_unsupported_milk(self):
        for cafe_id, sku in [('99', '4_350'), ('1', '4_999'), ('1', '1_350a'),
                             ('1', '4'), ('1', '4_350aa')]:
            self.assertIsNone(get_drink(cafe_id, sku))


class TestModeTests(unittest.TestCase):
    def test_order_at_night_and_confirmation_within_reservation(self):
        now = datetime(2026, 11, 13, 23, 55, tzinfo=LOCAL_TIMEZONE)
        with patch('app.settings.FOLLOW_SCHEDULE', False):
            self.assertEqual(available_breaks(now)[0].id, make_test_break(now).id)
            service = OrderService()
            draft = service.prepare(1, '1', '4_350a', make_test_break(now).id, now)
            order = service.confirm(1, draft.token, now + timedelta(seconds=60))
            self.assertEqual(order.draft.price, 330)
            self.assertIn('альтернативное молоко', order.draft.drink_name)

    def test_switching_schedule_on_rejects_test_confirmation(self):
        now = datetime(2026, 11, 13, 9, 10, tzinfo=LOCAL_TIMEZONE)
        service = OrderService()
        with patch('app.settings.FOLLOW_SCHEDULE', False):
            draft = service.prepare(1, '1', '4_350', make_test_break(now).id, now)
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            self.assertIsNone(find_break(make_test_break(now).id, now))
            with self.assertRaises(OrderError):
                service.confirm(1, draft.token, now)

    def test_schedule_still_closes_at_deadline(self):
        now = datetime(2026, 11, 13, 9, 40, tzinfo=LOCAL_TIMEZONE)
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            self.assertEqual(available_breaks(now), [])
        with patch('app.settings.FOLLOW_SCHEDULE', False):
            self.assertEqual(len(available_breaks(now)), 1)
            self.assertIsNone(find_break(daily_breaks(now.date())[0].id, now))
