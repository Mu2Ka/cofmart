"""OS locks are released even after a crash; stale files do not block startup."""
import os
import tempfile
from pathlib import Path


class AlreadyRunningError(RuntimeError):
    pass


class ProcessLock:
    def __init__(self, path: Path, message: str):
        self.path = path
        self.message = message
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open('a+b')
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise AlreadyRunningError(self.message) from None
        self.handle = handle
        return self

    def __exit__(self, *_):
        self.handle.close()


def bot_lock(token: str) -> ProcessLock:
    bot_id = token.split(':', 1)[0]
    if not bot_id.isdecimal():
        raise ValueError('Invalid Telegram bot ID')
    return ProcessLock(
        Path(tempfile.gettempdir()) / 'cofmart-locks' / f'bot-{bot_id}.lock',
        'Бот уже запущен. Используйте start-local.cmd; второй main.py запускать не нужно.',
    )
