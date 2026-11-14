"""Блокировка по username с запоминанием ID при первом обращении."""

import json
import logging
from pathlib import Path
import time
from uuid import uuid4
from app.process_lock import AlreadyRunningError, ProcessLock

from app.ordering import settings

BLOCK_MESSAGE = "Вы заблокированы в этом боте по решению создателя телеграмм-бота."
logger = logging.getLogger(__name__)


class BanService:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(__file__).resolve().parents[2] / ".local" / "blocked_users.json"
        self.legacy_path = None if path else Path(__file__).resolve().parents[2] / 'data' / 'blocked_users.json'
        self._ids: set[int] | None = None

    def load(self) -> set[int]:
        if self._ids is None:
            self._ids = set()
        for path in (self.path, self.legacy_path):
            if path is None:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = []
            if not isinstance(data, list) or any(type(value) is not int or value <= 0 for value in data):
                raise ValueError("data/blocked_users.json должен содержать список числовых Telegram ID.")
            self._ids.update(data)
        return self._ids

    def persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(40):
            try:
                with ProcessLock(self.path.with_suffix('.lock'), 'State is being updated'):
                    temporary = self.path.with_suffix('.' + uuid4().hex + '.tmp')
                    try:
                        temporary.write_text(json.dumps(sorted(self.load())) + '\n', encoding='utf-8')
                        temporary.replace(self.path)
                    finally:
                        temporary.unlink(missing_ok=True)
                return
            except AlreadyRunningError:
                time.sleep(0.005)
        raise OSError('Could not acquire state lock')

    def validate_configuration(self):
        if not isinstance(settings.BLOCKED_USER_IDS, (set, frozenset)) or any(
            type(value) is not int or value <= 0 for value in settings.BLOCKED_USER_IDS
        ):
            raise ValueError("BLOCKED_USER_IDS должен быть множеством положительных числовых ID.")
        if not isinstance(settings.BLOCKED_USERNAMES, (set, frozenset)) or any(
            not isinstance(value, str) or not value.strip().lstrip("@") for value in settings.BLOCKED_USERNAMES
        ):
            raise ValueError("BLOCKED_USERNAMES должен быть множеством непустых username.")
        self.load()

    def is_blocked(self, user_id: int, username: str | None = None) -> bool:
        if user_id in settings.BLOCKED_USER_IDS or user_id in self.load():
            return True
        names = {value.strip().lstrip("@").casefold() for value in settings.BLOCKED_USERNAMES}
        if username and username.lstrip("@").casefold() in names:
            self.load().add(user_id)
            try:
                self.persist()
            except OSError:
                # Сам отказ продолжает работать даже при недоступном диске.
                logger.exception("Не удалось сохранить ID заблокированного пользователя %s", user_id)
            return True
        return False


bans = BanService()
