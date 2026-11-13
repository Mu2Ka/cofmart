"""Переходы по настоящим клавиатурам aiogram без запросов в Telegram."""

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.types import Chat, Message, User

from app.catalog import PRODUCTS
from app.handlers import student
from app.keyboards import cafes_keyboard, categories_keyboard, drinks_keyboard, sizes_keyboard, milk_keyboard
from app.schedule import LOCAL_TIMEZONE
from app.services.orders import OrderService


class BotFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = OrderService()
        self.session = self.service.begin(1)
        now = datetime(2026, 11, 13, 23, 55, tzinfo=LOCAL_TIMEZONE)
        self.message = Message.model_construct(message_id=1, date=now, chat=Chat(id=1, type='private'))
        self.edit = AsyncMock()
        self.send = AsyncMock()
        for target, value in [
            ('app.handlers.student.orders', self.service),
            ('app.settings.FOLLOW_SCHEDULE', False),
            ('app.handlers.student.local_now', lambda: now),
            ('aiogram.types.Message.edit_text', self.edit),
            ('aiogram.types.Message.answer', self.send),
        ]:
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    async def click(self, data):
        callback = SimpleNamespace(data=data, from_user=SimpleNamespace(id=1),
                                   message=self.message, answer=AsyncMock(), bot=AsyncMock())
        if data.startswith('confirm:'):
            await student.confirm_callback(callback)
        elif data.startswith('comment:'):
            await student.add_comment(callback)
        elif data.startswith('skip_comment:'):
            await student.skip_comment(callback)
        else:
            await student.menu_callback(callback)
        return self.edit.call_args

    def button(self, label):
        keyboard = self.edit.call_args.kwargs['reply_markup']
        return next(button.callback_data for row in keyboard.inline_keyboard
                    for button in row if label in button.text)

    async def test_latte_with_alternative_milk_to_confirmed_order(self):
        await self.click(f'cafe:1:{self.session}')
        await self.click(self.button('Кофе'))
        await self.click(self.button('Латте ·'))
        await self.click(self.button('350 мл'))
        await self.click(self.button('Альтернативное'))
        self.assertIn('Итого: 330 ₽', self.edit.call_args.args[0])
        confirmation = self.button('Подтвердить')
        await self.click(confirmation)
        await self.click(confirmation)
        self.assertEqual(len(self.service.confirmed), 1)
        order = next(iter(self.service.confirmed.values()))
        self.assertEqual(order.draft.drink_name, 'Латте · 350 мл · альтернативное молоко')
        self.assertEqual(order.draft.price, 330)

    async def test_text_comment_appears_in_preview_and_final_order(self):
        await self.click(f'size:1:1_350:{self.session}')
        await self.click(self.button('комментарий'))
        text = 'со льдом <много> & без сахара'
        message = self.message.model_copy(update={
            'from_user': User(id=1, is_bot=False, first_name='Студент'), 'text': text,
        })
        await student.receive_comment(message)
        self.assertIn('со льдом &lt;много&gt; &amp; без сахара', self.send.call_args.args[0])
        keyboard = self.send.call_args.kwargs['reply_markup']
        confirmation = next(button.callback_data for row in keyboard.inline_keyboard
                            for button in row if 'Подтвердить' in button.text)
        await self.click(confirmation)
        self.assertIn('&lt;много&gt;', self.edit.call_args.args[0])
        self.assertEqual(next(iter(self.service.confirmed.values())).draft.comment, text)

    async def test_old_and_malformed_buttons_return_message(self):
        self.service.begin(1)
        await self.click(f'cafe:1:{self.session}')
        self.assertIn('устарели', self.edit.call_args.args[0])
        await self.click('product:1')
        self.assertIn('устарели', self.edit.call_args.args[0])

    def test_menu_buttons_fit_telegram_callback_limit(self):
        keyboards = [cafes_keyboard(self.session)]
        for cafe_id, products in PRODUCTS.items():
            keyboards.append(categories_keyboard(cafe_id, self.session))
            for product_id, product in products.items():
                keyboards.append(drinks_keyboard(cafe_id, product.category, self.session))
                keyboards.append(sizes_keyboard(cafe_id, product_id, self.session))
                if product.alternative_milk:
                    for size in product.sizes:
                        keyboards.append(milk_keyboard(cafe_id, f'{product_id}_{size}', self.session))
        for keyboard in keyboards:
            for row in keyboard.inline_keyboard:
                for button in row:
                    self.assertLessEqual(len(button.callback_data.encode('utf-8')), 64)
