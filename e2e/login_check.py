"""Checks the sign-in flow end to end against a LOCAL stack (never point it at production: it makes wrong-password
attempts on purpose).

    <python with playwright> e2e/login_check.py --email owner@example.com --password local-test-password-1 \
        [--base http://localhost:5173] [--axe frontend/node_modules/axe-core/axe.min.js]
"""
import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

results: list[tuple[bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    results.append((ok, name))
    print(f"[{'ok' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")


def shows(page: Page, text: str, timeout: int = 5000) -> bool:
    """is_visible() does not wait, so a check made right after a click can race the response."""
    try:
        page.get_by_text(text).wait_for(state="visible", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001 -- a timeout is the failure being reported
        return False


def fresh(browser, base, **kw):
    ctx = browser.new_context(**kw)
    page = ctx.new_page()
    problems: list[str] = []
    page.on("pageerror", lambda e: problems.append(str(e)[:120]))
    page.on("console", lambda m: problems.append(m.text[:120]) if m.type == "error" and "401" not in m.text and "400" not in m.text and "429" not in m.text else None)
    return ctx, page, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--axe")
    a = ap.parse_args()
    base = a.base

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. Wrong password: a specific, announced error; the form stays usable; the password is not echoed.
        ctx, page, problems = fresh(browser, base)
        page.goto(base + "/login")
        page.get_by_label("Email").fill(a.email)
        page.get_by_label("Password", exact=True).fill("definitely-wrong-password")
        page.get_by_role("button", name="Sign in").click()
        page.get_by_role("alert").get_by_text("Invalid email or password.").wait_for(timeout=8000)
        step("wrong password shows an announced error", True)
        step("the form is usable again after an error", page.get_by_role("button", name="Sign in").is_enabled())
        step("fields are marked invalid", page.get_by_label("Password", exact=True).get_attribute("aria-invalid") == "true")
        step("heading hierarchy: exactly one h1", page.locator("h1").count() == 1)
        step("a main landmark exists", page.locator("main").count() == 1)

        # 2. Show / hide password.
        page.get_by_role("button", name="Show password").click()
        step("show password reveals the field", page.get_by_label("Password", exact=True).get_attribute("type") == "text")
        page.get_by_role("button", name="Hide password").click()
        step("hide password masks it again", page.get_by_label("Password", exact=True).get_attribute("type") == "password")

        # 3. Keyboard only: type, Tab, Enter.
        page.get_by_label("Email").fill(a.email)
        page.get_by_label("Password", exact=True).fill(a.password)
        page.get_by_label("Password", exact=True).press("Enter")
        page.wait_for_url(base + "/", timeout=15000)
        step("Enter in the password field submits and lands on the overview", True)
        step("no console errors during sign-in", not problems, "; ".join(problems[:2]))

        # 4. Signed in: /login bounces to the app.
        page.goto(base + "/login")
        page.wait_for_url(base + "/", timeout=10000)
        step("visiting /login while signed in redirects to the app", True)
        ctx.close()

        # 5. Redirect back to the page you were going to.
        ctx, page, _ = fresh(browser, base)
        page.goto(base + "/reports?report=traffic")
        page.wait_for_url("**/login")
        page.get_by_label("Email").fill(a.email)
        page.get_by_label("Password", exact=True).fill(a.password)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/reports?report=traffic", timeout=15000)
        step("sign-in returns to the originally requested page (with its query)", True)

        # 6. Expired / revoked token: the app signs out instead of showing broken pages.
        page.evaluate("localStorage.setItem('helm_access_token', 'not-a-real-token')")
        page.goto(base + "/")
        page.wait_for_url("**/login", timeout=15000)
        step("an invalid stored token sends the user to sign in", True)
        step("and the bad token is removed", page.evaluate("localStorage.getItem('helm_access_token')") is None)
        ctx.close()

        # 7. Open-redirect guard.
        ctx, page, _ = fresh(browser, base)
        page.goto(base + "/login")
        page.evaluate("history.replaceState({usr: {from: '//evil.example'}, key: 'x', idx: 0}, '')")
        page.reload()
        page.get_by_label("Email").fill(a.email)
        page.get_by_label("Password", exact=True).fill(a.password)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url(re.compile(r"^" + re.escape(base) + r"/?$"), timeout=15000)
        step("a protocol-relative 'from' is ignored", page.url.startswith(base))
        ctx.close()

        # 8. Demo sign-in and double-click protection.
        ctx, page, _ = fresh(browser, base)
        page.goto(base + "/login")
        calls: list[str] = []
        page.on("request", lambda r: calls.append(r.url) if r.url.endswith("/api/auth/demo-login") else None)
        btn = page.get_by_role("button", name="Log in as Demo")
        btn.dblclick()
        page.wait_for_url(base + "/", timeout=15000)
        step("double-clicking the demo button sends one request", len(calls) == 1, f"{len(calls)} request(s)")
        ctx.close()

        # 9. Server errors and network loss read differently from a bad password.
        ctx, page, _ = fresh(browser, base)
        page.route("**/api/auth/login", lambda r: r.fulfill(status=500, body="{}"))
        page.goto(base + "/login")
        page.get_by_label("Email").fill(a.email)
        page.get_by_label("Password", exact=True).fill("whatever-password")
        page.get_by_role("button", name="Sign in").click()
        step("a 500 says Helm had a problem, not 'invalid password'", shows(page, "Helm had a problem on its side"))
        page.unroute("**/api/auth/login")
        page.route("**/api/auth/login", lambda r: r.abort())
        page.get_by_role("button", name="Sign in").click()
        step("no connection says so", shows(page, "Cannot reach Helm"))
        page.unroute("**/api/auth/login")
        page.route("**/api/auth/login", lambda r: r.fulfill(status=429, content_type="application/json", body='{"detail":"Too many attempts. Try again in 120 seconds."}'))
        page.get_by_role("button", name="Sign in").click()
        step("a 429 shows the server's wait time", shows(page, "Try again in 120 seconds"))
        ctx.close()

        # 10. The real limiter (separate client address so it does not affect later runs of the app).
        ctx, page, _ = fresh(browser, base, extra_http_headers={"cf-connecting-ip": "203.0.113.200"})
        page.goto(base + "/login")
        got429 = False
        for _ in range(14):
            page.get_by_label("Email").fill("nobody@example.com")
            page.get_by_label("Password", exact=True).fill("wrong-wrong-wrong")
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_function("() => !document.querySelector('button[type=submit]').disabled", timeout=8000)
            if page.get_by_text("Too many attempts").count():
                got429 = True
                break
        step("repeated wrong passwords get rate limited with a readable message", got429)
        ctx.close()

        # 11. Layout, theme and accessibility at phone and desktop widths.
        for theme in ("light", "dark"):
            for width in (375, 768, 1366):
                ctx, page, problems = fresh(browser, base, viewport={"width": width, "height": 800}, color_scheme=theme)
                page.goto(base + "/login", wait_until="networkidle")
                overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
                step(f"{theme} {width}px: no horizontal scroll", not overflow)
                if a.axe:
                    page.evaluate(Path(a.axe).read_text(encoding="utf-8"))
                    bad = page.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations.filter(v => ['serious','critical'].includes(v.impact)).map(v => v.id)")
                    step(f"{theme} {width}px: axe serious/critical", not bad, ", ".join(bad))
                ctx.close()
        browser.close()

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


sys.exit(main())
