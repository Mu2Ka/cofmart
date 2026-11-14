"""Run PostgreSQL, the bot and Mini App locally, with an HTTPS tunnel for Telegram."""
import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.db.session import Database
from app.services.catalog import CatalogService
from app.services.slots import SlotService

RUNTIME = ROOT / '.local'
STOP = RUNTIME / 'stop-request'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def run(*command, **kwargs):
    kwargs.setdefault('cwd', ROOT)
    subprocess.run([str(x) for x in command], check=True, creationflags=FLAGS, **kwargs)


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def postgres_bin():
    candidates = [
        RUNTIME / 'postgres-runtime' / 'bin',
        Path(os.environ.get('COFMART_POSTGRES_BIN', '.local/postgres-bin')),
        ROOT / '.qa/node_modules/@embedded-postgres/windows-x64/native/bin',
    ]
    candidates.extend(sorted(Path('C:/Program Files/PostgreSQL').glob('*/bin'), reverse=True))
    installed = shutil.which('pg_ctl')
    if installed:
        candidates.insert(0, Path(installed).parent)
    for directory in candidates:
        if (directory / 'pg_ctl.exe').exists():
            if '.qa' in directory.parts:
                portable = RUNTIME / 'postgres-runtime'
                if not portable.exists():
                    shutil.copytree(directory.parent, portable)
                return portable / 'bin'
            return directory.resolve()
    raise RuntimeError('PostgreSQL not found. Set COFMART_POSTGRES_BIN to its bin directory.')


def node_binary():
    installed = shutil.which('node')
    if installed:
        return installed
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    if bundled.exists():
        return str(bundled)
    raise RuntimeError('Node.js is not installed. Install Node.js 22.12+ and retry.')


def tunnel_url(process, log_path):
    for _ in range(120):
        if log_path.exists():
            text = log_path.read_text(encoding='utf-8', errors='replace')
            match = re.search(r'https://[a-z0-9-]+(?:\.app)?\.lhr\.life', text)
            if match:
                return match.group(0)
        if process.poll() is not None:
            break
        time.sleep(0.5)
    raise RuntimeError('HTTPS tunnel failed to start. See .local/tunnel.log.')


async def configure_telegram(token, public_url):
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    async with Bot(token=token, session=AiohttpSession(timeout=20)) as bot:
        me = await bot.get_me()
        saved = await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text='Заказать кофе', web_app=WebAppInfo(url=public_url),
        ))
        if not saved:
            raise RuntimeError('Telegram did not save the Mini App menu button.')
        # Telegram can briefly return the previous button after a successful update.
        for _ in range(10):
            button = await bot.get_chat_menu_button()
            if button.type == 'web_app' and button.web_app.url.rstrip('/') == public_url.rstrip('/'):
                break
            await asyncio.sleep(1)
        return me.username


async def prepare_database(url):
    connection = await asyncpg.connect(
        host=url.host, port=url.port or 5432, user=url.username,
        password=url.password, database='postgres', timeout=10,
    )
    try:
        if not await connection.fetchval('SELECT 1 FROM pg_database WHERE datname = $1', url.database):
            # Identifiers cannot be bound as SQL parameters; escape the configured name.
            name = url.database.replace('"', '""')
            await connection.execute(f'CREATE DATABASE "{name}"')
    finally:
        await connection.close()


async def cafes_without_times(settings):
    db = Database(settings.database_url)
    try:
        return [cafe.id for cafe in await CatalogService(db.sessions).cafes()
                if not await SlotService(db.sessions).available(cafe.id)]
    finally:
        await db.close()


def wait_for(url, process):
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError(f'Process exited before {url} was ready; see .local logs.')
        try:
            with LOCAL_HTTP.open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError(f'Timed out waiting for {url}; see .local logs.')


def serve():
    import msvcrt
    RUNTIME.mkdir(exist_ok=True)
    lock = (RUNTIME / 'run.lock').open('a+b')
    lock.write(b'0')
    lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise RuntimeError('Project is already running. Open your Telegram bot or use start-local.cmd --stop.') from None
    children = []
    handles = []
    pg = None
    started_postgres = False
    try:
        STOP.unlink(missing_ok=True)
        load_dotenv(ROOT / '.env')
        settings = get_settings()
        url = make_url(settings.database_url)
        if url.get_backend_name() != 'postgresql' or url.host not in {'localhost', '127.0.0.1'} or not url.database:
            raise RuntimeError('Local launcher requires DATABASE_URL pointing to a local PostgreSQL database.')
        for port in (8000,):
            if port_open(port):
                raise RuntimeError(f'Port {port} is in use. Stop the previous server before starting.')
        node = node_binary()
        vite = ROOT / 'frontend/node_modules/vite/bin/vite.js'
        if not vite.exists():
            raise RuntimeError('Frontend dependencies missing. Run pnpm install in frontend first.')
        tunnel_binary = shutil.which('ssh') or str(Path(os.environ['WINDIR']) / 'System32/OpenSSH/ssh.exe')
        if not Path(tunnel_binary).exists():
            raise RuntimeError('Windows OpenSSH Client is required for the Telegram HTTPS tunnel.')
        if not port_open(url.port or 5432):
            pg = postgres_bin()
            data = RUNTIME / 'postgres'
            if not (data / 'PG_VERSION').exists():
                password_file = RUNTIME / 'initial-password'
                if not url.password:
                    raise RuntimeError('Set a database password in DATABASE_URL.')
                password_file.write_text(url.password, encoding='utf-8')
                try:
                    with (RUNTIME / 'postgres-init.log').open('wb') as output:
                        run(pg / 'initdb.exe', '-D', data, '-U', url.username,
                            '-A', 'scram-sha-256', '--pwfile', password_file,
                            '--encoding=UTF8', '--locale=C', stdout=output, stderr=subprocess.STDOUT)
                finally:
                    password_file.unlink(missing_ok=True)
            run(pg / 'pg_ctl.exe', '-D', data, '-l', RUNTIME / 'postgres.log',
                '-o', f'-h 127.0.0.1 -p {url.port or 5432}', '-w', 'start')
            started_postgres = True
        asyncio.run(prepare_database(url))
        run(sys.executable, '-m', 'alembic', 'upgrade', 'head')
        run(sys.executable, '-m', 'app.db.seed')
        start = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(second=0, microsecond=0)
        for cafe in asyncio.run(cafes_without_times(settings)):
            run(sys.executable, '-m', 'app.db.manage', 'add-slots', '--cafe-id', cafe,
                '--start', start.isoformat(), '--count', 24, '--interval', 15, '--capacity', 5)

        print('Building Mini App for Telegram...', flush=True)
        build_env = {**os.environ, 'VITE_API_URL': '/api'}
        run(node, ROOT / 'frontend/node_modules/typescript/bin/tsc', '--noEmit', cwd=ROOT / 'frontend', env=build_env)
        run(node, vite, 'build', cwd=ROOT / 'frontend', env=build_env)

        def launch(name, command, extra=None, cwd=ROOT):
            output = (RUNTIME / f'{name}.log').open('ab')
            handles.append(output)
            process = subprocess.Popen(
                [str(x) for x in command], cwd=cwd, env={**os.environ, **(extra or {})},
                stdout=output, stderr=subprocess.STDOUT, creationflags=FLAGS,
            )
            children.append((name, process))
            return process

        uvicorn = [sys.executable, '-m', 'uvicorn']
        api = launch('web', [*uvicorn, 'app.web:create_web_app', '--factory', '--host', '127.0.0.1', '--port', '8000', '--no-access-log'])
        wait_for('http://127.0.0.1:8000/api/health', api)
        (RUNTIME / 'tunnel.log').write_text('', encoding='utf-8')
        tunnel = launch('tunnel', [
            tunnel_binary, '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
            '-o', f'UserKnownHostsFile="{(RUNTIME / "tunnel-known-hosts").as_posix()}"',
            '-o', 'IdentityFile=none', '-o', 'IdentityAgent=none',
            '-o', 'ServerAliveInterval=30', '-o', 'ExitOnForwardFailure=yes',
            '-R', '80:127.0.0.1:8000', 'nokey@localhost.run',
        ])
        public_url = tunnel_url(tunnel, RUNTIME / 'tunnel.log')
        wait_for(public_url + '/api/health', tunnel)
        username = asyncio.run(configure_telegram(settings.bot_token, public_url))
        bot = launch('bot', [sys.executable, ROOT / 'main.py'], {'MINI_APP_URL': public_url})
        (RUNTIME / 'processes.json').write_text(json.dumps({name: p.pid for name, p in children}), encoding='utf-8')
        (RUNTIME / 'mini-app-url.txt').write_text(public_url, encoding='utf-8')
        (RUNTIME / 'bot-username.txt').write_text(username, encoding='utf-8')
        print('\nPROJECT IS RUNNING', flush=True)
        print(f'Telegram: https://t.me/{username}', flush=True)
        print('Send /start, then tap Mini App, or use the Заказать кофе menu button.', flush=True)
        print(f'Mini App HTTPS: {public_url}', flush=True)
        print('API docs: http://localhost:8000/api/docs', flush=True)
        print('Keep this window open. Stop with Ctrl+C or start-local.cmd --stop.\n', flush=True)
        bot_warning = False
        while not STOP.exists():
            for name, process in children:
                if process.poll() is not None:
                    if name != 'bot':
                        raise RuntimeError(f'{name} exited. See .local/{name}.log')
                    if not bot_warning:
                        print('Bot stopped; see .local/bot.log. Mini App server remains available.', flush=True)
                        bot_warning = True
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nStopping local project...', flush=True)
    finally:
        for _, process in reversed(children):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        for output in handles:
            output.close()
        if started_postgres:
            run(pg / 'pg_ctl.exe', '-D', RUNTIME / 'postgres', '-m', 'fast', '-w', 'stop')
        (RUNTIME / 'processes.json').unlink(missing_ok=True)
        STOP.unlink(missing_ok=True)
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    if args.stop:
        if (RUNTIME / 'processes.json').exists():
            STOP.touch()
            print('Stop requested. Database files and orders are preserved.')
        else:
            print('No running local project found.')
    else:
        try:
            serve()
        except (RuntimeError, subprocess.CalledProcessError) as error:
            print(f'Local startup failed: {error}', file=sys.stderr)
            sys.exit(1)
