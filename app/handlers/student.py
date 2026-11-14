"""Compatibility imports; Telegram handlers now live in app.bot."""
from app.bot.handlers.student import cafe_callback, drink_callback, router, start

__all__ = ["router", "start", "cafe_callback", "drink_callback"]
