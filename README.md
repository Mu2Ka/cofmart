# Cofmart: бот и Telegram Mini App

Каркас студенческого приложения: `/start` → кнопка **Заказать кофе** → стартовая страница Mini App. Меню, заказы и оплата пока не подключены.

## Структура

```text
main.py                      # Бот и HTTP-сервер в одном процессе
app/config.py                # Настройки из .env
app/handlers/student.py      # Команда /start
app/keyboards.py             # Кнопка запуска Mini App
app/web.py                   # Раздача собранного frontend
mini_app/src/App.tsx         # Главный экран
mini_app/src/styles.css      # Оформление
mini_app/src/lib/telegram.ts # Подключение к Telegram Web App API
mini_app/dist/               # Результат сборки (не хранится в Git)
```

## 1. Подготовить окружение

Нужны Python 3.14+ и Node.js 22.12+ с npm. Node.js устанавливается отдельно от Python; пакет `npm` из pip не подходит. После установки Node.js перезапустите PyCharm и терминал. Проверка:

```powershell
node --version
npm.cmd --version
```

На Windows можно использовать `npm.cmd`, если PowerShell запрещает запуск `npm.ps1`.

В терминале PyCharm из корня проекта, с активированным Python-окружением:

```powershell
python -m pip install -r requirements.txt
cd mini_app
npm.cmd install
npm.cmd run build
cd ..
```

Сам каркас Vite уже создан, повторно выполнять `npm create vite` не нужно. Последующие установки выполняйте через `npm.cmd ci`, используя `package-lock.json`.

## 2. Настроить адрес Mini App

Для Windows есть готовый помощник. Из корня проекта выполните:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_tunnel.ps1
```

Он использует встроенный Windows OpenSSH и бесплатный сервис localhost.run без ваших SSH-ключей, запускает туннель в фоне и обновляет **только `MINI_APP_URL` в вашем существующем `.env`**, сохранив токен. Затем запустите `main.py` и отправьте `/start`. После перезагрузки компьютера помощник нужно запустить снова. Для остановки туннеля: `Stop-Process -Id (Get-Content .tools/ssh-tunnel.pid)`. Бесплатный адрес может меняться; при смене адреса остановите туннель, повторно запустите помощник и перезапустите бота. [Документация localhost.run](https://localhost.run/docs/faq/).

Telegram должен открывать **публичный HTTPS-адрес**. `localhost` на телефоне ведёт на сам телефон, а не на компьютер с ботом. Для разработки нужен HTTPS-туннель к `http://127.0.0.1:8080`, для постоянной работы — сервер с доменом и HTTPS.

Например, после отдельной установки Cloudflare Tunnel запустите во втором терминале:

```powershell
cloudflared tunnel --url http://127.0.0.1:8080
```

Скопируйте выданный адрес `https://….trycloudflare.com` в `MINI_APP_URL`. Туннель можно запустить до Python-сервера; до запуска сервера его страница будет недоступна. Быстрый туннель временный: при смене адреса обновите `.env`, перезапустите бота и отправьте `/start` заново. Уже отправленные кнопки сохраняют прежний URL.

Если `.env` уже существует, **сохраните текущий API_BOT** и добавьте остальные настройки. Иначе создайте `.env` по `.env.example`:

```dotenv
API_BOT=токен_из_BotFather
MINI_APP_URL=https://ваш-публичный-адрес
WEB_HOST=127.0.0.1
WEB_PORT=8080
```

Токен хранится только в Python-окружении, не во frontend. Текущий экран не использует персональные данные и не выполняет авторизацию. Перед добавлением пользовательских API необходимо проверять `initData` на backend.

## 3. Запустить

Запустите `main.py` кнопкой Run в PyCharm или командой из корня проекта:

```powershell
python main.py
```

Этот процесс одновременно запускает бота через polling и раздаёт frontend на `http://127.0.0.1:8080`. Отдельный Vite-сервер для этого режима не нужен. HTTPS-туннель остаётся запущенным отдельно.

Откройте **личный чат** с ботом, отправьте `/start`, нажмите **Заказать кофе**. Должно открыться окно Cofmart. Перед проверкой в Telegram убедитесь, что публичный адрес открывает ту же страницу в обычном браузере.

Не запускайте две копии polling одного бота одновременно. Остановка `main.py` останавливает и бота, и локальный HTTP-сервер.

## Разработка frontend

Для работы только над интерфейсом:

```powershell
cd mini_app
npm.cmd run dev
```

Откройте `http://127.0.0.1:5173` в браузере. Изменения видны сразу. Чтобы увидеть новую версию через Python-сервер и кнопку бота, повторите `npm.cmd run build` и переоткройте Mini App.

## Проверки

```powershell
python -m unittest discover -s tests -v
cd mini_app
npm.cmd run build
```

Документация: [Telegram Mini Apps](https://core.telegram.org/bots/webapps), [Vite](https://vite.dev/guide/), [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
