from app.core import ratelimit
from app.core.config import settings


async def _bad_login(client, ip="203.0.113.7"):
    return await client.post(
        "/api/auth/login",
        data={"username": "nobody@example.com", "password": "wrong-password-123"},
        headers={"cf-connecting-ip": ip},
    )


async def test_login_is_blocked_after_the_limit_with_retry_after(client):
    for _ in range(settings.login_rate_limit):
        assert (await _bad_login(client)).status_code == 400
    blocked = await _bad_login(client)
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert "Too many attempts" in blocked.json()["detail"]


async def test_the_limit_is_per_client_address(client):
    for _ in range(settings.login_rate_limit + 1):
        await _bad_login(client, ip="203.0.113.7")
    assert (await _bad_login(client, ip="198.51.100.9")).status_code == 400


async def test_a_good_login_still_works_below_the_limit_and_other_routes_are_not_limited(auth_client):
    for _ in range(settings.login_rate_limit + 5):
        assert (await auth_client.get("/api/users/me")).status_code == 200


async def test_the_window_expires():
    ip = "203.0.113.50"
    for i in range(settings.login_rate_limit):
        assert ratelimit.check("POST", "/api/auth/login", ip, now=1000.0 + i) is None
    assert ratelimit.check("POST", "/api/auth/login", ip, now=1000.0 + settings.login_rate_limit) is not None
    later = 1000.0 + settings.auth_rate_window_seconds + settings.login_rate_limit + 1
    assert ratelimit.check("POST", "/api/auth/login", ip, now=later) is None


async def test_demo_login_is_limited_separately_and_more_generously(client):
    codes = [(await client.post("/api/auth/demo-login", headers={"cf-connecting-ip": "203.0.113.77"})).status_code for _ in range(settings.demo_login_rate_limit + 1)]
    assert codes[:-1] == [200] * settings.demo_login_rate_limit
    assert codes[-1] == 429
