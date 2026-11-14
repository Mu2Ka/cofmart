from unittest.mock import AsyncMock, MagicMock

from app.api.routers.flow import notification
from tests.helpers import TOKEN


async def test_notification_uses_api_store_for_roles_and_message_queue(monkeypatch):
    bot = AsyncMock()
    bot.__aenter__.return_value = bot
    sender = AsyncMock()
    monkeypatch.setattr('app.api.routers.flow.Bot', MagicMock(return_value=bot))
    monkeypatch.setattr('app.bot.notifications.notify_staff', sender)
    order, store = object(), object()
    await notification('staff', order, TOKEN, store)
    sender.assert_awaited_once_with(bot, order, store=store)


async def test_notification_failure_after_commit_is_logged_not_raised(monkeypatch, caplog):
    bot = AsyncMock()
    bot.__aenter__.return_value = bot
    monkeypatch.setattr('app.api.routers.flow.Bot', MagicMock(return_value=bot))
    monkeypatch.setattr('app.bot.notifications.notify_student', AsyncMock(side_effect=OSError('offline')))
    await notification('student', object(), TOKEN, object())
    assert 'уведомление' in caplog.text
