import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from app.config import Settings, load_settings
from app.handlers.student import start
from app.web import create_web_app


class SettingsTests(unittest.TestCase):
    def test_public_https_url_required(self):
        for url in ("", "http://example.com", "https://localhost", "https://127.0.0.1"):
            with self.subTest(url=url), patch("app.config.load_dotenv"), patch.dict(
                os.environ, {"API_BOT": "test-token", "MINI_APP_URL": url}, clear=True
            ):
                with self.assertRaisesRegex(RuntimeError, "MINI_APP_URL"):
                    load_settings()

    def test_load_settings(self):
        with patch("app.config.load_dotenv"), patch.dict(
            os.environ,
            {"API_BOT": "test-token", "MINI_APP_URL": "https://coffee.example", "WEB_PORT": "8090"},
            clear=True,
        ):
            self.assertEqual(load_settings(), Settings("test-token", "https://coffee.example", web_port=8090))


class StartTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_opens_web_app(self):
        message = AsyncMock()
        message.chat.type = "private"
        await start(message, Settings("test-token", "https://coffee.example"))
        keyboard = message.answer.call_args.kwargs["reply_markup"]
        button = keyboard.inline_keyboard[0][0]
        self.assertEqual(button.text, "Заказать кофе")
        self.assertEqual(button.web_app.url, "https://coffee.example")
        self.assertIsNone(button.callback_data)

    async def test_group_does_not_get_web_app_button(self):
        message = AsyncMock()
        message.chat.type = "group"
        await start(message, Settings("test-token", "https://coffee.example"))
        self.assertNotIn("reply_markup", message.answer.call_args.kwargs)


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def test_serves_page_and_assets_without_exposing_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            dist = Path(directory)
            (dist / "index.html").write_text("<h1>Cofmart</h1>", encoding="utf-8")
            (dist / "assets").mkdir()
            (dist / "assets" / "app.js").write_text("console.log('cofmart')", encoding="utf-8")
            async with TestClient(TestServer(create_web_app(dist))) as client:
                page = await client.get("/")
                self.assertEqual(page.status, 200)
                self.assertIn("Cofmart", await page.text())
                self.assertEqual((await client.get("/assets/app.js")).status, 200)
                self.assertEqual((await client.get("/.env")).status, 404)

    def test_missing_build_explains_how_to_build(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "npm run build"):
                create_web_app(Path(directory))
