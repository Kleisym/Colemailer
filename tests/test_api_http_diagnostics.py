import io
import urllib.error
import pytest
from cole.api_autoreg import MyTelegramAuth, ApiAuthError

class FailureOpener:
    def __init__(self, body):
        self.body = body
    def open(self, req, timeout):
        raise urllib.error.HTTPError(req.full_url, 400, 'bad request', {}, io.BytesIO(self.body))

@pytest.mark.parametrize(('path','stage'), [('/auth/send_password','запрос кода'),('/auth/login','вход по коду'),('/apps','чтение приложения'),('/apps/create','создание приложения'),('/unexpected','запрос')])
def test_http_error_identifies_operation_without_body(path, stage):
    auth = MyTelegramAuth(opener=FailureOpener(b'{"text":"private-data-123456789"}'))
    with pytest.raises(ApiAuthError) as exc:
        auth._open('https://my.telegram.org' + path)
    assert f'HTTP 400' in str(exc.value)
    assert stage in str(exc.value)
    assert 'private-data' not in str(exc.value)
    assert '123456789' not in str(exc.value)

def test_http_error_shows_allowlisted_code_and_field():
    auth = MyTelegramAuth(opener=FailureOpener(b'{"error":"PHONE_CODE_INVALID", "field":"app_shortname"}'))
    with pytest.raises(ApiAuthError) as exc:
        auth._open('https://my.telegram.org/auth/login')
    assert 'PHONE_CODE_INVALID' in str(exc.value)
    assert 'app_shortname' in str(exc.value)

def test_http_error_does_not_echo_unknown_error_field_or_html():
    auth = MyTelegramAuth(opener=FailureOpener(b'{"error":"secret42", "field":"secretfield"}'))
    with pytest.raises(ApiAuthError) as exc:
        auth._open('https://my.telegram.org/apps/create')
    assert 'secret42' not in str(exc.value)
    assert 'secretfield' not in str(exc.value)
