"""Изолированная проверка настоящего Dispatcher. Сеть Telegram полностью подменена."""

import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher, F
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.handlers.entry import router as entry_router
from app.handlers.staff import router as staff_router
from app.handlers.student import router as student_router
from app.handlers.customer import router as customer_router
from app.middlewares import install_ban_middleware
from app.services.bans import BLOCK_MESSAGE, BanService
from app.schedule import test_break as make_test_break
from app.services.orders import orders
from app.services.customer import customer


async def check():
    session = AsyncMock(return_value=True)
    bot = Bot(token='123456:LOCAL_TEST_TOKEN', session=session)
    dp = Dispatcher()
    dp.message.filter(F.chat.type == 'private')
    dp.callback_query.filter(F.message.chat.type == 'private')
    dp.include_routers(entry_router, staff_router, customer_router, student_router)
    now = datetime.now(timezone.utc)

    def texts():
        return [getattr(call.args[1], 'text', '') or '' for call in session.call_args_list]

    with tempfile.TemporaryDirectory() as directory, \
            patch('app.settings.BLOCKED_USERNAMES', {'blocked_sample_one', 'blocked_sample_two'}), \
            patch('app.settings.FOLLOW_SCHEDULE', False), patch('app.settings.ADMIN_IDS', {900}), \
            patch('app.settings.BARISTA_CAFES', {101: {'1'}}):
        install_ban_middleware(dp, BanService(Path(directory) / 'blocked.json'))
        for index, (user_id, command, expected) in enumerate([
            (1, '/start', 'Выберите'), (1, '/student', 'Выберите кофейню'),
            (1, '/myorders', 'Мои последние'), (1, '/barista', 'не назначен'),
            (1, '/favorites', 'Избранные напитки'), (1, '/repeat', 'пока нет заказов'),
            (1, '/myid', 'Telegram ID'), (101, '/barista', 'Рабочая панель'),
            (1, '/admin', 'не назначен'), (900, '/admin', 'Панель администратора'),
            (1, '/grant_barista 1 1', 'только администратору'),
        ]):
            session.reset_mock()
            message = Message(message_id=index + 1, date=now, chat=Chat(id=user_id, type='private'),
                              from_user=User(id=user_id, is_bot=False, first_name='Test'), text=command)
            await dp.feed_update(bot, Update(update_id=index + 1, message=message))
            assert any(expected in text for text in texts()), (command, texts())

        for index, (user_id, data, expected) in enumerate([
            (900, 'role:admin', 'Панель администратора'),
            (101, 'staff_cafe:1', 'Активных заказов'),
            (101, 'staff_cafe:2', 'нет доступа'),
            (1, 'role:barista', 'не назначен'),
        ]):
            session.reset_mock()
            message = Message(message_id=100 + index, date=now, chat=Chat(id=user_id, type='private'),
                              from_user=User(id=123456, is_bot=True, first_name='Bot'), text='Role')
            query = CallbackQuery(id=f'local{index}', chat_instance='local',
                                  from_user=User(id=user_id, is_bot=False, first_name='Test'),
                                  message=message, data=data)
            await dp.feed_update(bot, Update(update_id=100 + index, callback_query=query))
            assert any(expected in text for text in texts()), (data, texts())

        # Ввод лимита должен попасть в staff-router, а не в обработчик комментариев студента.
        from app.schedule import local_now
        pickup = make_test_break(local_now())
        session.reset_mock()
        message = Message(message_id=150, date=now, chat=Chat(id=101, type='private'),
                          from_user=User(id=123456, is_bot=True, first_name='Bot'), text='Slots')
        query = CallbackQuery(id='slots', chat_instance='local',
                              from_user=User(id=101, is_bot=False, first_name='Barista'),
                              message=message, data=f'staff_editslots:1:{pickup.id}')
        await dp.feed_update(bot, Update(update_id=150, callback_query=query))
        assert any('Отправьте целое число' in text for text in texts())
        message = Message(message_id=151, date=now, chat=Chat(id=101, type='private'),
                          from_user=User(id=101, is_bot=False, first_name='Barista'), text='4')
        await dp.feed_update(bot, Update(update_id=151, message=message))
        assert orders.slots('1', pickup.id, local_now()).limit == 4
        session.reset_mock()
        message = Message(message_id=152, date=now, chat=Chat(id=1, type='private'),
                          from_user=User(id=1, is_bot=False, first_name='Student'), text='/student')
        await dp.feed_update(bot, Update(update_id=152, message=message))
        labels = [button.text for row in session.call_args.args[1].reply_markup.inline_keyboard for button in row]
        assert any('CaVa' in label and '4/4' in label for label in labels)

        # Проверяем маршрутизацию новых возможностей, не вызывая обработчики напрямую.
        draft = orders.prepare(1, '1', '1_350', pickup.id, local_now(), comment='со льдом')
        order = orders.confirm(1, draft.token, local_now())
        for status in ['preparing', 'ready', 'done']:
            order = orders.transition(101, order.number, status, order.revision, local_now())
        for data, expected in [(f'favorite_add:{order.reference}', 'добавлен в избранное'),
                               (f'rate:{order.reference}:5', 'Спасибо за оценку'),
                               (f'repeat:{order.reference}', 'Проверьте заказ')]:
            session.reset_mock()
            query = CallbackQuery(id='customer', chat_instance='local',
                                  from_user=User(id=1, is_bot=False, first_name='Student'),
                                  message=message, data=data)
            await dp.feed_update(bot, Update(update_id=170, callback_query=query))
            assert any(expected in text for text in texts()), (data, texts())
        assert orders.drafts[1].comment == 'со льдом'
        assert customer.list(1)

        session.reset_mock()
        message = Message(message_id=200, date=now, chat=Chat(id=-100, type='group', title='Test'),
                          from_user=User(id=900, is_bot=False, first_name='Admin'), text='/admin')
        await dp.feed_update(bot, Update(update_id=200, message=message))
        session.assert_not_awaited()

        for index, username in enumerate(['blocked_sample_one', 'Blocked_Sample_Two']):
            for command in ['/start', '/student', '/roles', '/admin', '/barista', '/myid', '/myorders', 'со льдом']:
                session.reset_mock()
                user = User(id=700 + index, is_bot=False, first_name='Blocked', username=username)
                message = Message(message_id=300, date=now, chat=Chat(id=user.id, type='private'),
                                  from_user=user, text=command)
                await dp.feed_update(bot, Update(update_id=300, message=message))
                assert texts() == [BLOCK_MESSAGE], (username, command, texts())
            # После смены username запомненный ID по-прежнему заблокирован.
            session.reset_mock()
            user = user.model_copy(update={'username': 'renamed_account'})
            query = CallbackQuery(id='blocked', chat_instance='local', from_user=user,
                                  message=message, data='staff_cafe:1')
            await dp.feed_update(bot, Update(update_id=400, callback_query=query))
            assert texts() == [BLOCK_MESSAGE]
            assert session.call_args.args[1].show_alert is True
    await bot.session.close()
    print('Real Dispatcher: commands, roles, permissions and private chat filter OK')


if __name__ == '__main__':
    asyncio.run(check())
