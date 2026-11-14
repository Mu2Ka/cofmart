import unittest

from sqlalchemy import BigInteger, DateTime

from app.config import database_url_from_values
from app.db.model import Base, Cafe, User


class DatabaseModelTests(unittest.TestCase):
    def test_telegram_id_is_bigint_without_autoincrement(self):
        column = User.__table__.c.id
        self.assertIsInstance(column.type, BigInteger)
        self.assertTrue(column.primary_key)
        self.assertFalse(column.autoincrement)

    def test_schema_defaults_and_nullable_fields(self):
        self.assertTrue({"users", "cafes", "orders", "order_drafts", "slot_limits", "favorites"}
                        <= set(Base.metadata.tables))
        self.assertTrue(User.__table__.c.username.nullable)
        created = User.__table__.c.created_at
        self.assertIsInstance(created.type, DateTime)
        self.assertTrue(created.type.timezone)
        self.assertIsNotNone(created.server_default)
        self.assertFalse(Cafe.__table__.c.accepts_orders.nullable)
        self.assertEqual(str(Cafe.__table__.c.accepts_orders.server_default.arg), "true")


class DatabaseConfigTests(unittest.TestCase):
    def values(self):
        return {"DB_NAME": "cofmart_test", "DB_USER": "test_user", "DB_PASSWORD": "a@b:%/ #"}

    def test_special_password_is_not_interpolated_into_url(self):
        values = self.values()
        url = database_url_from_values(values)
        self.assertEqual(url.password, values['DB_PASSWORD'])
        self.assertNotIn(values['DB_PASSWORD'], str(url))
        self.assertEqual(url.drivername, 'postgresql+asyncpg')
        self.assertEqual(url.port, 5432)

    def test_missing_values_have_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'DB_PASSWORD'):
            database_url_from_values({'DB_NAME': 'cofmart', 'DB_USER': 'user'})

    def test_invalid_port_is_rejected(self):
        for port in ['abc', '0', '-1', '65536']:
            with self.subTest(port=port), self.assertRaises(ValueError):
                database_url_from_values(self.values() | {'DB_PORT': port})
