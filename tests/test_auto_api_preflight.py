import json
import pytest
from tests.test_android_auto_api import load_bridge
from cole import api_autoreg

@pytest.mark.parametrize('has_cookie', [False, True])
def test_preflight_only_for_cookie(monkeypatch, tmp_path, has_cookie):
    calls = []
    class FakeAuth:
        def __init__(self, cookie_path): self.logged = has_cookie
        def has_session(self): calls.append('has_session'); return self.logged
        def fetch_app(self):
            calls.append('fetch_app')
            assert self.logged, 'attempted fetch without authenticated cookie'
            return {'api_id': 1111, 'api_hash':'a' * 32}
        def send_code(self, phone): calls.append('send_code')
        def sign_in(self, code): calls.append('sign_in'); self.logged = True
        def save_cookies(self): pass
        def close(self): pass
    bridge=load_bridge()
    monkeypatch.setattr(api_autoreg,'MyTelegramAuth',FakeAuth)
    monkeypatch.setattr(bridge,'_ensure_storage',lambda _: None)
    monkeypatch.setattr(bridge,'_ask_code',lambda _: 'code')
    monkeypatch.setattr(bridge,'_save_credentials',lambda *args: None)
    result=json.loads(bridge.auto_api('+79991111111',str(tmp_path)))
    assert result['ok']
    assert ('send_code' in calls) is (not has_cookie)
    assert calls.index('has_session') < calls.index('fetch_app')


def test_cookie_fetch_http_error_is_not_hidden(monkeypatch,tmp_path):
    calls=[]
    class FakeAuth:
        def __init__(self,cookie_path): pass
        def has_session(self): return True
        def fetch_app(self): calls.append('fetch_app'); raise api_autoreg.ApiAuthError('HTTP 400 от my.telegram.org (чтение приложения)')
        def send_code(self,phone): calls.append('send_code')
        def close(self): pass
    bridge=load_bridge()
    monkeypatch.setattr(api_autoreg,'MyTelegramAuth',FakeAuth)
    monkeypatch.setattr(bridge,'_ensure_storage',lambda _: None)
    result=json.loads(bridge.auto_api('+79991111111',str(tmp_path)))
    assert not result['ok']
    assert 'HTTP 400' in result['error']
    assert calls == ['fetch_app']

def test_cookie_create_error_is_not_hidden(monkeypatch, tmp_path):
    calls = []
    class FakeAuth:
        def __init__(self, cookie_path): pass
        def has_session(self): return True
        def fetch_app(self): return None
        def create_app(self, **kwargs):
            calls.append('create_app')
            raise api_autoreg.ApiAuthError('HTTP 400 от my.telegram.org (создание приложения)')
        def send_code(self, phone): calls.append('send_code')
        def close(self): pass
    bridge = load_bridge()
    monkeypatch.setattr(api_autoreg, 'MyTelegramAuth', FakeAuth)
    monkeypatch.setattr(bridge, '_ensure_storage', lambda _: None)
    result = json.loads(bridge.auto_api('+79991111111', str(tmp_path)))
    assert result['ok'] is False
    assert 'создание приложения' in result['error']
    assert calls == ['create_app']
