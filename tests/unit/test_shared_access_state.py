from concurrent.futures import ThreadPoolExecutor
import json

from app.ordering.bans import BanService
from app.ordering import settings


def test_separate_service_instances_observe_new_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,'BLOCKED_USER_IDS',set())
    monkeypatch.setattr(settings,'BLOCKED_USERNAMES',{'blocked_sample_one'})
    first, second = BanService(tmp_path/'state.json'), BanService(tmp_path/'state.json')
    assert first.load() == set()
    assert second.is_blocked(123,'blocked_sample_one')
    assert first.is_blocked(123,'renamed')


def test_parallel_writers_merge_ids_without_losing_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,'BLOCKED_USER_IDS',set())
    monkeypatch.setattr(settings,'BLOCKED_USERNAMES',{'blocked_sample_one'})
    path = tmp_path/'state.json'
    def learn(uid):
        return BanService(path).is_blocked(uid,'blocked_sample_one')
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert all(pool.map(learn,range(1,13)))
    assert BanService(path).load() == set(range(1,13))


def test_prior_file_remains_effective_after_restructure(tmp_path):
    old = tmp_path/'old.json'
    old.write_text(json.dumps([123]),encoding='utf-8')
    service = BanService(tmp_path/'new.json')
    service.legacy_path = old
    assert service.is_blocked(123,'renamed')
