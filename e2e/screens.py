"""Screenshot matrix: every page and project tab, light and dark, at 375 / 768 / 1366, as the owner and the demo user.

    <python with playwright> e2e/screens.py --label baseline [--base http://localhost:5173] \
        [--email owner@example.com --password local-test-password-1]

Writes e2e/out/<label>/<role>-<theme>-<width>-<page>.png, logs console errors and failed requests per view, and
runs axe-core when --axe <path to axe.min.js> is given (serious and critical violations are listed).
Without --email only the demo user is captured. Reads only.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parent / "out"
WIDTHS = [375, 768, 1366]
TABS = ["Indexing", "Rankings", "Keywords", "Sitemaps"]
TOKEN_KEY = "helm_access_token"


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_function("() => !document.body.innerText.includes('Loading')", timeout=20000)
    page.wait_for_timeout(300)


def run_axe(page: Page, axe_src: str) -> list[str]:
    page.evaluate(axe_src)
    result = page.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations")
    return [f"{v['impact']}: {v['id']} ({len(v['nodes'])})" for v in result if v["impact"] in ("serious", "critical")]


def capture(browser, base, role, token, theme, width, out, axe_src):
    problems = []
    ctx = browser.new_context(viewport={"width": width, "height": 850}, color_scheme=theme)
    ctx.add_init_script(f"localStorage.setItem('{TOKEN_KEY}', {json.dumps(token)}); localStorage.setItem('helm_theme', '{theme}')")
    page = ctx.new_page()
    page.on("console", lambda m: problems.append(f"console: {m.text[:150]}") if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(f"exception: {str(e)[:150]}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status} {r.url[:100]}") if r.status >= 400 else None)

    def shot(name):
        settle(page)
        page.screenshot(path=str(out / f"{role}-{theme}-{width}-{name}.png"), full_page=True)
        if axe_src:
            problems.extend(f"axe {name}: {v}" for v in run_axe(page, axe_src))

    for name, path in [("overview", "/"), ("content", "/content"), ("traffic", "/traffic"), ("tasks", "/tasks"),
                       ("reports", "/reports"), ("settings", "/settings")]:
        page.goto(base + path, wait_until="networkidle")
        shot(name)
    # A pipeline project with every tab.
    page.goto(base + "/", wait_until="networkidle")
    settle(page)
    page.locator('a[href^="/projects/"]').first.click()
    page.wait_for_url("**/projects/*")
    shot("project")
    for tab in TABS:
        btn = page.get_by_role("button", name=tab, exact=True)
        if btn.count():
            btn.first.click()
            shot(f"project-{tab.lower()}")
    ctx.close()
    return problems


def get_token(base, email=None, password=None):
    import urllib.parse
    import urllib.request

    if email:
        data = urllib.parse.urlencode({"username": email, "password": password}).encode()
        req = urllib.request.Request(base + "/api/auth/login", data=data)
    else:
        req = urllib.request.Request(base + "/api/auth/demo-login", data=b"", method="POST")
    return json.load(urllib.request.urlopen(req))["access_token"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--axe")
    a = ap.parse_args()
    out = OUT / a.label
    out.mkdir(parents=True, exist_ok=True)
    axe_src = Path(a.axe).read_text(encoding="utf-8") if a.axe else None
    roles = [("demo", get_token(a.base))]
    if a.email:
        roles.insert(0, ("owner", get_token(a.base, a.email, a.password)))
    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Prove the real login form works for the owner, once.
        if a.email:
            page = browser.new_page()
            page.goto(a.base + "/login", wait_until="networkidle")
            page.get_by_label("Email").fill(a.email)
            page.get_by_label("Password", exact=True).fill(a.password)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_url(a.base + "/", timeout=15000)
            print("[ok] owner login form")
            page.close()
        for role, token in roles:
            for theme in ("light", "dark"):
                for width in WIDTHS:
                    probs = capture(browser, a.base, role, token, theme, width, out, axe_src)
                    total += len(probs)
                    print(f"{role} {theme} {width}: {len(probs)} problem(s)")
                    for pr in probs[:8]:
                        print("   ", pr)
        # The login page itself, signed out.
        for theme in ("light", "dark"):
            for width in WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": 850}, color_scheme=theme)
                ctx.add_init_script(f"localStorage.setItem('helm_theme', '{theme}')")
                pg = ctx.new_page()
                pg.goto(a.base + "/login", wait_until="networkidle")
                pg.screenshot(path=str(out / f"login-{theme}-{width}.png"), full_page=True)
                ctx.close()
        browser.close()
    print(f"done: {total} problem(s); images in {out}")


main()
