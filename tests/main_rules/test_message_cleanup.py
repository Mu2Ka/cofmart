import asyncio
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import DeleteMessage, EditMessageText
from aiogram.types import Chat, Message

from app.bot.message_cleanup import (
    answer_notice, delete_due_messages, expire_message, message_cleanup_worker,
)
from app.bot.notifications import send
from app.bot.ui import show, show_notice


class DeletionStore:
    def __init__(self):
        self.rows = {}

    async def schedule_deletion(self, bot_id, chat_id, message_id, delete_at):
        self.rows[bot_id, chat_id, message_id] = SimpleNamespace(
            bot_id=bot_id, chat_id=chat_id, message_id=message_id, delete_at=delete_at)

    async def cancel_deletion(self, *key):
        self.rows.pop(key, None)

    async def due_deletions(self, bot_id, now):
        return [(cid, mid) for (bid, cid, mid), row in self.rows.items()
                if bid == bot_id and row.delete_at <= now]

    @asynccontextmanager
    async def locked_deletion(self, bot_id, chat_id, message_id, now):
        key = (bot_id, chat_id, message_id)
        row = self.rows.get(key)
        if row and row.delete_at > now:
            row = None
        session = SimpleNamespace(delete=AsyncMock(side_effect=lambda _: self.rows.pop(key)))
        yield session, row


class MessageCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = Bot(token="123456:LOCAL_TEST_TOKEN", session=AsyncMock())
        self.delete = AsyncMock(return_value=True)
        self.store = DeletionStore()
        self.message = Message.model_construct(message_id=10, chat=Chat(id=321, type="private"))
        self.message.as_(self.bot)
        self.key = (self.bot.id, 321, 10)
        for target, value in [("app.ordering.persistent.get_store", lambda: self.store),
                              ("aiogram.Bot.delete_message", self.delete),
                              ("app.ordering.settings.SERVICE_MESSAGE_TTL_SECONDS", 60),
                              ("app.ordering.settings.NOTIFICATION_TTL_SECONDS", 300)]:
            patched = patch(target, value)
            patched.start()
            self.addCleanup(patched.stop)
        self.addAsyncCleanup(self.bot.session.close)

    async def test_notice_expires_and_only_due_messages_are_deleted(self):
        with patch.object(Message, "answer", AsyncMock(return_value=self.message)):
            await answer_notice(self.message, "Сохранено")
        row = self.store.rows[self.key]
        remaining = (row.delete_at - datetime.now(timezone.utc)).total_seconds()
        self.assertTrue(58 <= remaining <= 60)
        await delete_due_messages(self.bot, now=row.delete_at - timedelta(seconds=1))
        self.delete.assert_not_awaited()
        await delete_due_messages(self.bot, now=row.delete_at)
        self.delete.assert_awaited_once_with(chat_id=321, message_id=10)
        self.assertEqual(self.store.rows, {})

    async def test_order_notification_has_its_own_lifetime(self):
        with patch.object(Bot, "send_message", AsyncMock(return_value=self.message)):
            await send(self.bot, 321, "Заказ готов", "my_orders", "Открыть")
        remaining = (self.store.rows[self.key].delete_at - datetime.now(timezone.utc)).total_seconds()
        self.assertTrue(298 <= remaining <= 300)

    async def test_opened_card_cancels_timer_even_when_text_is_unchanged(self):
        await expire_message(self.message, 60)
        error = TelegramBadRequest(method=EditMessageText(text="x"), message="message is not modified")
        with patch.object(Message, "edit_text", AsyncMock(side_effect=error)):
            await show(SimpleNamespace(message=self.message), "Текущая карточка")
        self.assertEqual(self.store.rows, {})
        await delete_due_messages(self.bot, now=datetime.now(timezone.utc) + timedelta(hours=1))
        self.delete.assert_not_awaited()

    async def test_fallback_after_deleted_card_schedules_new_message(self):
        replacement = self.message.model_copy(update={"message_id": 11})
        error = TelegramBadRequest(method=EditMessageText(text="x"), message="message to edit not found")
        with patch.object(Message, "edit_text", AsyncMock(side_effect=error)), \
                patch.object(Message, "answer", AsyncMock(return_value=replacement)):
            await show_notice(SimpleNamespace(message=self.message), "Оформление отменено")
        self.assertEqual(set(self.store.rows), {(self.bot.id, 321, 11)})

    async def test_zero_lifetime_keeps_message(self):
        await expire_message(self.message, 60)
        await expire_message(self.message, 0)
        self.assertEqual(self.store.rows, {})

    async def test_nonprivate_and_unbound_messages_are_not_scheduled(self):
        group = self.message.model_copy(update={"chat": Chat(id=-321, type="group", title="Group")})
        unbound = Message.model_construct(message_id=99, chat=Chat(id=321, type="private"))
        await expire_message(group, 60)
        await expire_message(unbound, 60)
        self.assertEqual(self.store.rows, {})

    async def test_retry_after_reschedules_and_stops_batch(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(*self.key, now)
        await self.store.schedule_deletion(self.bot.id, 321, 11, now)
        self.delete.side_effect = TelegramRetryAfter(method=DeleteMessage(chat_id=321, message_id=10),
                                                     message="retry", retry_after=17)
        delay = await delete_due_messages(self.bot, now=now)
        self.assertEqual(delay, 17)
        self.assertEqual(self.delete.await_count, 1)
        self.assertGreaterEqual(self.store.rows[self.key].delete_at, now + timedelta(seconds=17))

    async def test_network_failure_keeps_job_for_retry(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(*self.key, now)
        self.delete.side_effect = TelegramNetworkError(method=DeleteMessage(chat_id=321, message_id=10), message="offline")
        self.assertEqual(await delete_due_messages(self.bot, now=now), 30)
        self.assertGreaterEqual(self.store.rows[self.key].delete_at, now + timedelta(seconds=30))

    async def test_already_deleted_message_does_not_block_queue(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(*self.key, now)
        self.delete.side_effect = TelegramBadRequest(method=DeleteMessage(chat_id=321, message_id=10),
                                                     message="message to delete not found")
        await delete_due_messages(self.bot, now=now)
        self.assertEqual(self.store.rows, {})

    async def test_forbidden_deletion_is_logged_and_removed_from_queue(self):
        now = datetime.now(timezone.utc)
        await self.store.schedule_deletion(*self.key, now)
        self.delete.side_effect = TelegramForbiddenError(method=DeleteMessage(chat_id=321, message_id=10),
                                                         message="bot was blocked")
        with self.assertLogs("app.bot.message_cleanup", level="WARNING"):
            await delete_due_messages(self.bot, now=now)
        self.assertEqual(self.store.rows, {})

    async def test_worker_is_cancelled_on_shutdown(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def loop(bot):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with patch("app.bot.message_cleanup.cleanup_loop", loop):
            async with message_cleanup_worker(self.bot):
                await asyncio.wait_for(started.wait(), timeout=1)
        self.assertTrue(cancelled.is_set())
