"""Rate limits are counted per visitor, and the health check is never limited.

Behind a hosting proxy every request reaches the service from the proxy's own address,
so counting by that address made all visitors share one limit (50 an hour, 10 logins a
minute) and a few requests locked everyone out. The visitor's address is read from the
host's header only where that is configured or the host is known to set it."""

import pytest

HEADER = 'CF-Connecting-IP'
BAD_LOGIN = {'username': 'admin', 'password': 'wrong'}


def attempts(client, n, ip=None):
    headers = {HEADER: ip} if ip else {}
    return [client.post('/api/auth/login', json=BAD_LOGIN, headers=headers).status_code for _ in range(n)]


class TestOffByDefault:
    def test_the_header_is_ignored_unless_it_is_enabled(self, client):
        """A caller must not be able to dodge the limits by writing a header"""
        codes = [client.post('/api/auth/login', json=BAD_LOGIN, headers={HEADER: f'203.0.113.{i}'}).status_code for i in range(12)]
        assert codes[:10] == [401] * 10
        assert 429 in codes[10:]


class TestPerVisitor:
    @pytest.fixture
    def per_visitor(self, make_api, monkeypatch):
        monkeypatch.setenv('CLIENT_IP_HEADER', HEADER)
        return make_api()[0].app.test_client()

    def test_one_visitor_reaching_the_limit_does_not_lock_out_another(self, per_visitor):
        first = attempts(per_visitor, 12, ip='203.0.113.10')
        assert first[:10] == [401] * 10 and 429 in first[10:]
        assert attempts(per_visitor, 3, ip='203.0.113.11') == [401] * 3

    def test_the_same_visitor_is_still_limited(self, per_visitor):
        assert 429 in attempts(per_visitor, 15, ip='198.51.100.7')

    def test_ipv6_addresses_work(self, per_visitor):
        assert attempts(per_visitor, 2, ip='2001:db8::1') == [401, 401]

    @pytest.mark.parametrize('junk', ['not-an-ip', '1.2.3', '999.1.1.1', "1.1.1.1, 8.8.8.8", '<script>'])
    def test_a_header_that_is_not_an_address_falls_back_to_the_connecting_address(self, per_visitor, junk):
        codes = [per_visitor.post('/api/auth/login', json=BAD_LOGIN, headers={HEADER: junk + ' ' * i}).status_code for i in range(12)]
        assert 429 in codes[10:]

    def test_a_missing_header_falls_back_to_the_connecting_address(self, per_visitor):
        assert 429 in attempts(per_visitor, 12)


class TestHostDetection:
    def test_render_switches_it_on_without_any_other_setting(self, make_api, monkeypatch):
        monkeypatch.setenv('RENDER', 'true')
        client = make_api()[0].app.test_client()
        assert 429 in attempts(client, 12, ip='203.0.113.20')
        assert attempts(client, 2, ip='203.0.113.21') == [401, 401]

    def test_an_empty_setting_turns_it_off_even_on_render(self, make_api, monkeypatch):
        monkeypatch.setenv('RENDER', 'true')
        monkeypatch.setenv('CLIENT_IP_HEADER', '')
        client = make_api()[0].app.test_client()
        codes = [client.post('/api/auth/login', json=BAD_LOGIN, headers={HEADER: f'203.0.113.{i}'}).status_code for i in range(12)]
        assert 429 in codes[10:]

    def test_another_header_can_be_named(self, make_api, monkeypatch):
        monkeypatch.setenv('CLIENT_IP_HEADER', 'X-Real-IP')
        client = make_api()[0].app.test_client()
        codes = [client.post('/api/auth/login', json=BAD_LOGIN, headers={'X-Real-IP': '192.0.2.5'}).status_code for _ in range(12)]
        assert 429 in codes[10:]
        assert client.post('/api/auth/login', json=BAD_LOGIN, headers={'X-Real-IP': '192.0.2.6'}).status_code == 401


class TestHealthCheck:
    def test_the_health_check_is_never_rate_limited(self, client):
        codes = {client.get('/api/health').status_code for _ in range(120)}
        assert codes == {200}

    def test_other_routes_are_still_limited(self, client, auth):
        """The statistics route allows 200 an hour; the 201st request is refused"""
        codes = [client.get('/api/statistics/fraud', headers=auth).status_code for _ in range(205)]
        assert codes[:200] == [200] * 200
        assert 429 in codes[200:]
