"""Удаление временных ответов. Очередь PostgreSQL переживает перезапуск бота."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import (
    TelegramAPIError, TelegramBadRequest, TelegramNetworkError,
    TelegramRetryAfter, TelegramServerError,
)
from aiogram.types import Message
from sqlalchemy.exc import SQLAlchemyError

from app.ordering import settings
from app.ordering import persistent

logger = logging.getLogger(__name__)
POLL_SECONDS = 5


def message_key(message):
    if not isinstance(message, Message) or message.chat.type != "private":
        return None
    try:
        bot = message.bot
    except RuntimeError:
        return None
    if bot is None:
        return None
    return bot.id, message.chat.id, message.message_id


async def expire_message(message, seconds: int, *, store=None):
    key = message_key(message)
    if key is None:
        return
    try:
        store = store or persistent.get_store()
        if seconds == 0:
            await store.cancel_deletion(*key)
        else:
            await store.schedule_deletion(*key, datetime.now(timezone.utc) + timedelta(seconds=seconds))
    except (SQLAlchemyError, OSError, TimeoutError):
        # Ошибка очистки чата не должна отменять уже сохранённый заказ.
        logger.warning("Не удалось запланировать удаление сообщения.")


async def keep_message(message):
    """Карточка стала активным экраном — прежний таймер больше не действует."""
    await expire_message(message, 0)


async def answer_notice(message: Message, text: str, **kwargs):
    result = await message.answer(text, **kwargs)
    await expire_message(result, settings.SERVICE_MESSAGE_TTL_SECONDS)
    return result


async def delete_due_messages(bot, store=None, now=None):
    store = store or persistent.get_store()
    now = now or datetime.now(timezone.utc)
    for chat_id, message_id in await store.due_deletions(bot.id, now):
        # Перепроверяем задачу под блокировкой: её могли отменить при открытии карточки.
        async with store.locked_deletion(bot.id, chat_id, message_id, now) as (session, row):
            if row is None:
                continue
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except TelegramRetryAfter as error:
                row.delete_at = datetime.now(timezone.utc) + timedelta(seconds=max(1, error.retry_after))
                # RetryAfter ограничивает весь поток запросов этого бота.
                return max(1, error.retry_after)
            except (TelegramNetworkError, TelegramServerError):
                row.delete_at = datetime.now(timezone.utc) + timedelta(seconds=30)
                return 30
            except TelegramBadRequest as error:
                if "message to delete not found" not in str(error).lower():
                    logger.warning("Telegram не разрешил удалить сообщение %s в чате %s.", message_id, chat_id)
                await session.delete(row)
            except TelegramAPIError:
                # Например, человек заблокировал бота или Telegram уже запрещает удаление.
                logger.warning("Удаление сообщения %s в чате %s недоступно.", message_id, chat_id)
                await session.delete(row)
            else:
                await session.delete(row)


async def cleanup_loop(bot):
    while True:
        delay = POLL_SECONDS
        try:
            delay = await delete_due_messages(bot) or POLL_SECONDS
        except (SQLAlchemyError, OSError, TimeoutError):
            logger.warning("Очередь удаления сообщений временно недоступна.")
        await asyncio.sleep(delay)


@asynccontextmanager
async def message_cleanup_worker(bot):
    task = asyncio.create_task(cleanup_loop(bot), name="message-cleanup")
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
