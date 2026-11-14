import unittest
from unittest.mock import AsyncMock, patch

from aiogram.types import CallbackQuery, Chat, Message, User
from sqlalchemy.exc import OperationalError

from app.bot.full_middlewares import DatabaseMiddleware


class DatabaseMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = AsyncMock()
        self.handler = AsyncMock(return_value="handled")
        self.user = User(id=321, is_bot=False, first_name="Student", username="test_student")
        self.message = Message.model_construct(message_id=1, chat=Chat(id=321, type="private"),
            from_user=User(id=999, is_bot=True, first_name="Bot"))
        self.callback = CallbackQuery.model_construct(id="test", chat_instance="test", data="roles",
            message=self.message, from_user=self.user)
        self.middleware = DatabaseMiddleware()

    async def test_callback_registers_author_of_click(self):
        with patch("app.ordering.persistent.get_store", lambda: self.store):
            result = await self.middleware(self.handler, self.callback, {})
        self.store.register.assert_awaited_once_with(self.user)
        self.handler.assert_awaited_once_with(self.callback, {})
        self.assertEqual(result, "handled")

    async def test_unavailable_database_does_not_run_handler_or_use_memory(self):
        self.store.register.side_effect = OperationalError(None, None, RuntimeError("unavailable"))
        with patch("app.ordering.persistent.get_store", lambda: self.store), \
                patch.object(Message, "answer", AsyncMock()) as answer, self.assertLogs(level="ERROR"):
            await self.middleware(self.handler, self.callback, {})
        self.handler.assert_not_awaited()
        self.assertIn("базе данных", answer.call_args.args[0])

    async def test_group_message_does_not_register_or_handle(self):
        message = self.message.model_copy(update={"chat": Chat(id=-321, type="group", title="Group"),
                                                  "from_user": self.user})
        with patch("app.ordering.persistent.get_store", lambda: self.store):
            await self.middleware(self.handler, message, {})
        self.store.register.assert_not_awaited()
        self.handler.assert_not_awaited()
