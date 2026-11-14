"""Интеграционные тесты в отдельной временной схеме PostgreSQL.

Запуск: $env:COFMART_TEST_POSTGRES='1'; python -m unittest tests.test_postgres_flow -v
Таблицы рабочей схемы public не изменяются; временная схема удаляется после теста.
"""

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from pathlib import Path

from alembic import command
from alembic.config import Config

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_database_url
from app.db.model import DraftRecord, OrderRecord, User, MessageDeletionRecord
from app.db.seed import seed_cafes
from app.db.store import PostgresStore
from app.schedule import LOCAL_TIMEZONE, order_windows, available_breaks, test_break as make_test_break
from app.services.cafes import CafeError
from app.services.orders import OrderError, SlotEditExpired
from app.services.persistent import PersistentService
from app.services.roles import AccessError
from app.message_cleanup import delete_due_messages


@unittest.skipUnless(os.getenv("COFMART_TEST_POSTGRES") == "1", "Включите COFMART_TEST_POSTGRES=1 для PostgreSQL")
class PostgresFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "cofmart_test_" + uuid4().hex
        self.control = create_async_engine(get_database_url(), hide_parameters=True)
        self.addAsyncCleanup(self.control.dispose)
        async with self.control.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.addAsyncCleanup(self.drop_schema)
        self.engine = create_async_engine(get_database_url(), hide_parameters=True,
            connect_args={"server_settings": {"search_path": self.schema}})
        self.addAsyncCleanup(self.engine.dispose)
        def migrate(connection):
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        async with self.engine.begin() as connection:
            await connection.run_sync(migrate)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.factory.begin() as session:
            await seed_cafes(session)
        self.store = PostgresStore(self.factory)
        self.orders = PersistentService("orders", self.store)
        self.customer = PersistentService("customer", self.store)
        self.cafes = PersistentService("cafes", self.store)
        self.roles = PersistentService("roles", self.store)
        self.now = datetime(2031, 1, 2, 9, 20, tzinfo=LOCAL_TIMEZONE)
        self.pickup = make_test_break(self.now)
        for name, value in [("FOLLOW_SCHEDULE", False), ("ADMIN_IDS", {900}),
                            ("BARISTA_CAFES", {101: {"1"}, 102: {"1"}, 201: {"2"}}),
                            ("DEFAULT_SLOTS_PER_BREAK", 10), ("SLOT_RESERVATION_SECONDS", 120)]:
            patched = patch("app.settings." + name, value)
            patched.start()
            self.addCleanup(patched.stop)
        for uid in (1, 2, 101, 102, 201, 900):
            await self.store.register(SimpleNamespace(id=uid, first_name="Test", username=None))

    async def drop_schema(self):
        # Имя создаётся только через uuid4, никогда не берётся из пользовательского ввода.
        if not self.schema.startswith("cofmart_test_") or len(self.schema) != 45:
            raise RuntimeError("Unexpected test schema name")
        async with self.control.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))

    async def draft(self, uid=1, comment="со льдом"):
        session = await self.orders.begin(uid)
        return await self.orders.prepare(uid, "1", "1_350", self.pickup.id, self.now,
                                         comment=comment, session=session)

    async def order(self, uid=1):
        draft = await self.draft(uid)
        return await self.orders.confirm(uid, draft.token, self.now)

    async def test_profile_and_confirmed_order_survive_new_store_and_connection(self):
        await self.store.register(SimpleNamespace(id=1, first_name="Новое имя", username="new_name"))
        draft = await self.draft()
        await self.orders.start_comment(1, draft.token, self.now)
        # Новый экземпляр не содержит прежних словарей или ORM-сессии.
        second = PersistentService("orders", PostgresStore(self.factory))
        self.assertEqual(await second.waiting_comment(1), draft.token)
        draft = await second.save_comment(1, draft.token, "много льда <test>", self.now)
        order, created = await second.confirm_once(1, draft.token, self.now)
        self.assertTrue(created)
        await self.engine.dispose()
        restored = await self.orders.own_order(1, order.reference)
        self.assertEqual(restored, order)
        self.assertEqual(restored.draft.comment, "много льда <test>")
        self.assertEqual(restored.draft.price, 165)
        self.assertEqual(restored.draft.pickup.starts_at.hour, 0)
        self.assertEqual(await second.for_user(1), [order])
        async with self.factory() as session:
            user = await session.get(User, 1)
            self.assertEqual((user.first_name, user.username), ("Новое имя", "new_name"))
            self.assertIsNotNone(user.created_at.tzinfo)

    async def test_two_confirmations_create_one_order_and_one_notification_decision(self):
        draft = await self.draft()
        results = await asyncio.gather(*[
            self.orders.confirm_once(1, draft.token, self.now) for _ in range(4)])
        self.assertEqual(len({order.number for order, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(OrderRecord)), 1)
            self.assertEqual(await session.scalar(select(func.count()).select_from(DraftRecord)), 0)
        with self.assertRaises(OrderError):
            await self.orders.confirm(2, draft.token, self.now)

    async def test_last_slot_is_atomic_and_expired_reservation_is_released(self):
        await self.orders.set_slot_limit(101, "1", self.pickup.id, 1, self.now)
        results = await asyncio.gather(self.draft(1), self.draft(2), return_exceptions=True)
        self.assertEqual(sum(isinstance(result, OrderError) for result in results), 1)
        first = next(result for result in results if not isinstance(result, Exception))
        summary = await self.orders.slots("1", self.pickup.id, self.now)
        self.assertEqual((summary.confirmed, summary.reserved, summary.free), (0, 1, 0))
        later = self.now + timedelta(seconds=121)
        with self.assertRaises(OrderError):
            await self.orders.confirm(first.user_id, first.token, later)
        self.assertEqual((await self.orders.slots("1", self.pickup.id, later)).free, 1)

    async def test_roles_pause_stoplist_favorites_rating_and_repeat_persist(self):
        order = await self.order()
        favorite = await self.customer.add_order(1, order.reference)
        await self.customer.add_order(1, order.reference)
        for status in ("preparing", "ready", "done"):
            order = await self.orders.transition(101, order.number, status, order.revision, self.now)
        await self.orders.rate(1, order.reference, 4)
        await self.orders.rate(1, order.reference, 5)
        self.assertEqual(await self.orders.rating_summary(101, "1"), (1, 5.0))
        self.assertEqual(len(await self.customer.list(1)), 1)
        await self.cafes.set_open(101, "1", False)
        with self.assertRaises(OrderError):
            await self.customer.prepare(1, "f", favorite.key, self.pickup.id, self.now)
        await self.cafes.set_open(101, "1", True)
        await self.cafes.set_available(101, "1", "1", False)
        with self.assertRaises(OrderError):
            await self.customer.prepare(1, "r", order.reference, self.pickup.id, self.now)
        await self.cafes.set_available(101, "1", "1", True)
        repeated = await self.customer.prepare(1, "r", order.reference, self.pickup.id, self.now)
        self.assertEqual(repeated.comment, "со льдом")
        await self.roles.assign(900, 101, "1", False)
        self.assertEqual(await self.roles.barista_cafes(101), set())
        with self.assertRaises(AccessError):
            await self.cafes.set_open(101, "1", False)
        # Назначение ещё не зарегистрированному человеку не требует выдуманного имени в users.
        await self.roles.assign(900, 777, "2", True)
        self.assertEqual(await self.roles.cafes_for(777), {"2"})
        await self.customer.remove(1, favorite.key)
        self.assertEqual(await self.customer.list(1), [])

    async def test_concurrent_baristas_revision_privacy_and_slot_revision(self):
        order = await self.order()
        with self.assertRaises(OrderError):
            await self.orders.own_order(2, order.reference)
        results = await asyncio.gather(*[
            self.orders.transition(uid, order.number, "preparing", 0, self.now)
            for uid in (101, 102)], return_exceptions=True)
        self.assertEqual(sum(isinstance(result, OrderError) for result in results), 1)
        revision = (await self.orders.slots("1", self.pickup.id, self.now)).revision
        await self.orders.set_slot_limit(101, "1", self.pickup.id, 5, self.now, revision)
        with self.assertRaises(SlotEditExpired):
            await self.orders.set_slot_limit(102, "1", self.pickup.id, 8, self.now, revision)
        with self.assertRaises(OrderError):
            await self.orders.set_slot_limit(101, "1", self.pickup.id, 0, self.now)

    async def test_stale_session_and_cutoff_are_rechecked_in_transaction(self):
        stale = await self.orders.begin(1)
        await self.orders.begin(1)
        with self.assertRaises(OrderError):
            await self.orders.prepare(1, "1", "1_350", self.pickup.id, self.now, session=stale)
        self.assertFalse(await self.orders.cancel_session(1, stale))
        with patch("app.settings.FOLLOW_SCHEDULE", True):
            pickup = order_windows(self.now.date())[0]
            near_cutoff = pickup.closes_at - timedelta(seconds=30)
            draft = await self.orders.prepare(1, "1", "1_350", pickup.id, near_cutoff)
            with self.assertRaises(OrderError):
                await self.orders.confirm(1, draft.token, pickup.closes_at)
        self.assertEqual((await self.orders.slots("1", pickup.id, self.now)).reserved, 0)

    async def test_database_write_failure_rolls_back_reservation(self):
        await self.orders.begin(1)
        with patch("app.db.store.pack_draft", return_value={"bad": object()}):
            with self.assertRaises(SQLAlchemyError):
                await self.orders.prepare(1, "1", "1_350", self.pickup.id, self.now)
        self.assertEqual((await self.orders.slots("1", self.pickup.id, self.now)).free, 10)
        self.assertEqual(await self.orders.for_user(1), [])

    async def test_completed_capacity_requires_manual_staff_addition(self):
        await self.orders.set_slot_limit(101, "1", self.pickup.id, 1, self.now)
        order = await self.order()
        for status in ("preparing", "ready", "done"):
            order = await self.orders.transition(101, order.number, status, order.revision, self.now)
        other = PersistentService("orders", PostgresStore(self.factory))
        summary = await other.slots("1", self.pickup.id, self.now)
        self.assertEqual((summary.free, summary.completed, summary.active), (0, 1, 0))
        with self.assertRaises(AccessError):
            await other.add_slots(1, "1", self.pickup.id, 2, self.now, summary.revision)
        await other.add_slots(101, "1", self.pickup.id, 2, self.now, summary.revision)
        with self.assertRaises(SlotEditExpired):
            await other.add_slots(101, "1", self.pickup.id, 2, self.now, summary.revision)
        restored = await self.orders.slots("1", self.pickup.id, self.now)
        self.assertEqual((restored.limit, restored.free, restored.completed), (3, 2, 1))

    async def test_live_order_night_and_long_break_survive_reconnect_and_pause(self):
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            night = self.now.replace(hour=23, minute=59, second=30)
            pickup = available_breaks(night)[0]
            draft = await self.orders.prepare(1, '1', '1_350', pickup.id, night)
            restored = PersistentService('orders', PostgresStore(self.factory))
            order = await restored.confirm(1, draft.token, night + timedelta(seconds=60))
            self.assertEqual((await restored.slots('1', pickup.id, night + timedelta(seconds=60))).free, 9)
            during_long_break = self.now.replace(hour=10, minute=35)
            live = available_breaks(during_long_break)[0]
            second = await restored.prepare(2, '1', '1_350', live.id, during_long_break)
            await restored.confirm(2, second.token, during_long_break)
            before_pause = self.now.replace(hour=11, minute=29, second=30)
            stale = await restored.prepare(2, '1', '1_350', live.id, before_pause)
            with self.assertRaises(OrderError):
                await restored.confirm(2, stale.token, self.now.replace(hour=11, minute=30))
            self.assertEqual((await restored.own_order(1, order.reference)).status, 'new')

    async def test_cutoff_rechecks_server_clock_after_database_wait(self):
        with patch('app.settings.FOLLOW_SCHEDULE', True):
            pickup = available_breaks(self.now)[0]
            before = pickup.closes_at - timedelta(seconds=30)
            draft = await self.orders.prepare(1, '1', '1_350', pickup.id, before)
            timed_store = PostgresStore(self.factory, clock=lambda: pickup.closes_at)
            timed = PersistentService('orders', timed_store)
            # В обработчике время было допустимым, но к выполнению операции настала пауза.
            with self.assertRaises(OrderError):
                await timed.confirm(1, draft.token, before)
            with self.assertRaises(OrderError):
                await timed.prepare(2, '1', '1_350', pickup.id, before)
            self.assertEqual(await self.orders.for_user(1), [])

    async def test_message_queue_persists_reschedule_and_separates_bots(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(123, 321, 10, now + timedelta(minutes=5))
        await self.store.schedule_deletion(123, 321, 10, now)
        await self.store.schedule_deletion(999, 321, 10, now)
        await self.store.schedule_deletion(123, 321, 11, now + timedelta(minutes=5))
        restored = PostgresStore(self.factory)
        self.assertEqual(await restored.due_deletions(123, now), [(321, 10)])
        bot = SimpleNamespace(id=123, delete_message=AsyncMock(return_value=True))
        await delete_due_messages(bot, restored, now)
        bot.delete_message.assert_awaited_once_with(chat_id=321, message_id=10)
        self.assertEqual(await restored.due_deletions(999, now), [(321, 10)])
        await restored.cancel_deletion(123, 321, 11)
        async with self.factory() as session:
            self.assertEqual(await session.scalar(select(func.count()).select_from(MessageDeletionRecord)), 1)

    async def test_concurrent_cleanup_workers_delete_message_once(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(123, 321, 10, now)
        started, release = asyncio.Event(), asyncio.Event()

        async def delete_message(**kwargs):
            started.set()
            await release.wait()
            return True

        bot = SimpleNamespace(id=123, delete_message=AsyncMock(side_effect=delete_message))
        first = asyncio.create_task(delete_due_messages(bot, self.store, now))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
            await asyncio.wait_for(delete_due_messages(bot, self.store, now), timeout=3)
        finally:
            release.set()
            await first
        self.assertEqual(bot.delete_message.await_count, 1)
        self.assertEqual(await self.store.due_deletions(123, now), [])

    async def test_cancelled_worker_preserves_job_for_next_start(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(123, 321, 10, now)
        started = asyncio.Event()

        async def delete_message(**kwargs):
            started.set()
            await asyncio.Event().wait()

        bot = SimpleNamespace(id=123, delete_message=AsyncMock(side_effect=delete_message))
        task = asyncio.create_task(delete_due_messages(bot, self.store, now))
        try:
            await asyncio.wait_for(started.wait(), timeout=3)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        restored = PostgresStore(self.factory)
        self.assertEqual(await restored.due_deletions(123, now), [(321, 10)])
        bot.delete_message = AsyncMock(return_value=True)
        await delete_due_messages(bot, restored, now)
        self.assertEqual(await restored.due_deletions(123, now), [])

    async def test_real_dispatcher_registers_student_and_persists_order(self):
        from aiogram import Bot, Dispatcher, F
        from aiogram.types import CallbackQuery, Chat, Message, Update, User as TelegramUser
        from app.handlers import customer, entry, staff, student
        from app.middlewares import install_database_middleware

        telegram = AsyncMock(return_value=True)
        bot = Bot(token="123456:LOCAL_TEST_TOKEN", session=telegram)
        dp = Dispatcher()
        dp.message.filter(F.chat.type == "private")
        dp.callback_query.filter(F.message.chat.type == "private")
        install_database_middleware(dp)
        dp.include_routers(entry.router, staff.router, customer.router, student.router)
        user = TelegramUser(id=555, is_bot=False, first_name="Student", username="student_test")
        message = Message(message_id=1, date=self.now, chat=Chat(id=555, type="private"),
                          from_user=user, text="/student")
        try:
            with patch("app.services.persistent.get_store", lambda: self.store), \
                    patch("app.handlers.student.local_now", lambda: self.now):
                await dp.feed_update(bot, Update(update_id=1, message=message))
                token = await self.orders.session(555)
                query = CallbackQuery(id="choose", chat_instance="test", from_user=user,
                                      message=message, data=f"size:1:1_350:{token}")
                await dp.feed_update(bot, Update(update_id=2, callback_query=query))
                draft = (await self.orders.view()).drafts[555]
                query = query.model_copy(update={"id": "confirm", "data": f"confirm:{draft.token}"})
                await dp.feed_update(bot, Update(update_id=3, callback_query=query))
                self.assertEqual(len(await self.orders.for_user(555)), 1)
                async with self.factory() as session:
                    self.assertEqual((await session.get(User, 555)).username, "student_test")
                    self.assertEqual(await session.scalar(select(func.count()).select_from(MessageDeletionRecord)), 1)
                query = query.model_copy(update={"id": "history", "data": "my_orders"})
                await dp.feed_update(bot, Update(update_id=4, callback_query=query))
                async with self.factory() as session:
                    self.assertEqual(await session.scalar(select(func.count()).select_from(MessageDeletionRecord)), 0)
        finally:
            await bot.session.close()
