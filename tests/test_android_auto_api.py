import importlib.util
import json
from pathlib import Path


def load_bridge():
    path = Path(__file__).resolve().parents[1] / 'android/app/src/main/python/bot_bridge.py'
    spec = importlib.util.spec_from_file_location('test_android_bot_bridge', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auto_api_cookie_is_scoped_to_phone(monkeypatch, tmp_path):
    from cole import api_autoreg
    bridge = load_bridge()
    sessions = {}
    requested = []

    class FakeAuth:
        def __init__(self, cookie_path):
            self.path = cookie_path
            self.logged_in = self.path in sessions
        def fetch_app(self):
            return sessions.get(self.path)
        def has_session(self):
            return self.logged_in
        def send_code(self, phone):
            requested.append(phone)
            self.phone = phone
        def sign_in(self, code):
            assert code == 'code'
            self.logged_in = True
            sessions[self.path] = {'api_id': len(sessions) + 1, 'api_hash': 'a' * 32}
        def save_cookies(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(api_autoreg, 'MyTelegramAuth', FakeAuth)
    monkeypatch.setattr(bridge, '_ensure_storage', lambda _: None)
    monkeypatch.setattr(bridge, '_ask_code', lambda _: 'code')
    monkeypatch.setattr(bridge, '_save_credentials', lambda *args: None)
    first = json.loads(bridge.auto_api('+79991111111', str(tmp_path)))
    second = json.loads(bridge.auto_api('+79992222222', str(tmp_path)))
    again = json.loads(bridge.auto_api('+79991111111', str(tmp_path)))
    assert first['api_id'] == again['api_id']
    assert first['api_id'] != second['api_id']
    assert requested == ['+79991111111', '+79992222222']
    assert len(sessions) == 2
    assert all('+7999' not in path for path in sessions)
    assert all(Path(path).name != 'tg_api_cookies.txt' for path in sessions)
