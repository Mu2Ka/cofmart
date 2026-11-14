from datetime import datetime, timezone
from unittest.mock import AsyncMock

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update, User

from app.bot.handlers import orders, student
from app.bot.middlewares import ServicesMiddleware
from app.services.orders import OrderService
from tests.helpers import TOKEN


async def test_old_callbacks_and_full_checkout_without_api(db):
    bot = Bot(TOKEN)
    real_session = bot.session
    bot.session = AsyncMock()
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    middleware = ServicesMiddleware(db.sessions)
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    dp.include_routers(student.router, orders.router)
    user = User(id=1001, is_bot=False, first_name="Тест")
    message = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=1001, type="private"), from_user=user,
                      text="/start", entities=[MessageEntity(type="bot_command", offset=0, length=6)])
    state = dp.fsm.get_context(bot=bot, chat_id=1001, user_id=1001)
    index = 1

    async def click(value):
        nonlocal index
        index += 1
        await dp.feed_update(bot, Update(update_id=index, callback_query=CallbackQuery(
            id=str(index), from_user=user, chat_instance="test", message=message, data=value)))

    try:
        await dp.feed_update(bot, Update(update_id=1, message=message))
        await click("cafe:1")
        await click("drink:1:1")
        await click("drink:1:2")
        await click("cart")
        await click("checkout")
        await click("slot:1")
        checkout = (await state.get_data())["checkout"]
        await click(f'confirm:{checkout["key"]}')
        await click(f'confirm:{checkout["key"]}')
        history = await OrderService(db.sessions).list(1001)
        assert len(history) == 1
        assert history[0].total_minor == 44500
        assert len(history[0].items) == 2
        await click("history")
        await click("drink:garbage")
        await click("cafe:unknown")
        await click("drink:1:missing")
        methods = [call.args[1] for call in bot.session.call_args_list]
        messages = [x for x in methods if isinstance(x, SendMessage)]
        assert any("Вы выбрали Бамбл в кофейне CaVa." in x.text for x in messages)
        assert any("Не удалось определить напиток" in x.text for x in messages)
        assert any("Такого напитка нет" in x.text for x in messages)
        first_buttons = messages[0].reply_markup.inline_keyboard
        assert first_buttons[0][0].callback_data == "cafe:1"
        assert first_buttons[1][0].callback_data == "cafe:2"
    finally:
        await dp.storage.close()
        await dp.fsm.events_isolation.close()
        await real_session.close()
        student.router._parent_router = None
        orders.router._parent_router = None
