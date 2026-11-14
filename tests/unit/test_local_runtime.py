import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from app.process_lock import ProcessLock
from scripts.run_local import healthy, latest_tunnel_url


def test_lock_blocks_another_process_and_releases_on_exit(tmp_path):
    path = tmp_path / 'bot.lock'
    program = """
import sys
from pathlib import Path
from app.process_lock import ProcessLock, AlreadyRunningError
try:
    with ProcessLock(Path(sys.argv[1]), 'already running'):
        pass
except AlreadyRunningError:
    sys.exit(42)
"""
    with ProcessLock(path, 'already running'):
        assert subprocess.run([sys.executable, '-c', program, str(path)]).returncode == 42
    assert subprocess.run([sys.executable, '-c', program, str(path)]).returncode == 0


def test_tunnel_rotation_uses_latest_url():
    log = 'https://admin.localhost.run/\nhttps://old.app.lhr.life\nhttps://new.app.lhr.life'
    assert latest_tunnel_url(log) == 'https://new.app.lhr.life'


def test_http_200_no_tunnel_is_not_healthy():
    class Handler(BaseHTTPRequestHandler):
        body = b'no tunnel'

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(self.body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        assert not healthy(url)
        Handler.body = b'{"status":"ok"}'
        assert healthy(url)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
