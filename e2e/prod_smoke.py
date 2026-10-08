"""Production smoke test for Helm, run with Playwright for Python against the live site.

    <python with playwright and chromium> e2e/prod_smoke.py [--base https://helm.billtoolbox.com] [--headed]

Logs in as the read-only demo account (no credentials needed), visits every page and every project tab, and
FAILS on any console error, uncaught page exception or failed/4xx/5xx network request. Screenshots go to
e2e/out/. The crawler-service virtualenv already has Playwright and Chromium:

    D:\\staging\\crawler-service\\.venv\\Scripts\\python.exe e2e/prod_smoke.py

Owner-only checks (the Refresh now button, token creation) need the owner's login. They run only when both
HELM_E2E_EMAIL and HELM_E2E_PASSWORD are set in the environment, and they only read: the refresh button is
checked for presence, never clicked, so the smoke test cannot spend quota or change data.
"""
import argparse
import os
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parent / "out"
PROJECT_TABS = ["Indexing", "Rankings", "Keywords", "Sitemaps"]
# Responses that are normal for a signed-out visitor and must not fail the run.
EXPECTED_STATUS = {("GET", "/api/users/me", 401)}


class Collector:
    def __init__(self, page: Page, base: str):
        self.problems: list[str] = []
        self.requests = 0
        page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text[:200]} @ {page.url}") if m.type == "error" else None)
        page.on("pageerror", lambda e: self.problems.append(f"page exception: {str(e)[:200]} @ {page.url}"))
        page.on("requestfailed", lambda r: self.problems.append(f"request failed: {r.method} {r.url[:120]} ({r.failure})"))
        page.on("response", self._response)
        self.base = base

    def _response(self, r):
        self.requests += 1
        path = r.url.replace(self.base, "")
        if r.status >= 400 and (r.request.method, path.split("?")[0], r.status) not in EXPECTED_STATUS:
            self.problems.append(f"HTTP {r.status}: {r.request.method} {path[:120]}")


def settle(page: Page) -> None:
    """Network idle is not enough: a section fires its fetch after it renders. Wait until no "Loading" text is left."""
    page.wait_for_load_state("networkidle")
    page.wait_for_function("() => !document.body.innerText.includes('Loading')", timeout=20000)


def step(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'ok' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    return ok


def run(base: str, headed: bool) -> int:
    OUT.mkdir(exist_ok=True)
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(viewport={"width": 1366, "height": 850})
        page = context.new_page()
        seen = Collector(page, base)

        page.goto(f"{base}/login", wait_until="networkidle")
        failures += not step("login page renders", page.get_by_role("button", name="Log in as Demo").is_visible())
        page.screenshot(path=str(OUT / "01-login.png"))

        page.get_by_role("button", name="Log in as Demo").click()
        page.wait_for_url(f"{base}/", timeout=20000)
        page.wait_for_load_state("networkidle")
        links = page.locator('a[href^="/projects/"]')
        links.first.wait_for(timeout=15000)  # the list is fetched after the route renders
        failures += not step("overview lists demo projects", links.count() > 0, f"{links.count()} project links")
        page.screenshot(path=str(OUT / "02-overview.png"))

        for label, path in [("Traffic", "/traffic"), ("Reports", "/reports"), ("Settings", "/settings"), ("Tasks", "/tasks")]:
            page.get_by_role("link", name=label).first.click()
            page.wait_for_url(f"{base}{path}", timeout=15000)
            settle(page)
            body = page.locator("main, body").first.inner_text()
            failures += not step(f"{label} page renders", len(body.strip()) > 40 and "something went wrong" not in body.lower())
            page.screenshot(path=str(OUT / f"03-{label.lower()}.png"))

        # A pipeline project has the section tabs; open the first project that does.
        page.goto(f"{base}/", wait_until="networkidle")
        hrefs = [links.nth(i).get_attribute("href") for i in range(links.count())]
        tabs_checked = False
        for href in hrefs:
            page.goto(f"{base}{href}", wait_until="networkidle")
            if not page.get_by_role("navigation", name="Project sections").count():
                continue
            tabs_checked = True
            for tab in PROJECT_TABS:
                page.get_by_role("navigation", name="Project sections").get_by_role("button", name=tab).click()
                settle(page)
                body = page.locator("main, body").first.inner_text()
                bad = any(s in body.lower() for s in ("could not load", "failed to load", "something went wrong", "internal error"))
                failures += not step(f"project tab {tab}", not bad and len(body.strip()) > 40)
                page.screenshot(path=str(OUT / f"04-tab-{tab.lower()}.png"))
            break
        failures += not step("a pipeline project with tabs exists", tabs_checked)

        if os.environ.get("HELM_E2E_EMAIL") and os.environ.get("HELM_E2E_PASSWORD"):
            failures += check_owner(page, base, hrefs)
        else:
            print("[skip] owner checks (set HELM_E2E_EMAIL and HELM_E2E_PASSWORD to run them)")

        for problem in seen.problems:
            print(f"[FAIL] {problem}")
        failures += len(seen.problems)
        print(f"{seen.requests} network responses observed, {failures} problem(s)")
        browser.close()
    return 1 if failures else 0


def check_owner(page: Page, base: str, hrefs: list[str]) -> int:
    """Read-only owner checks. The credentials come from the environment and are never printed."""
    failures = 0
    page.context.clear_cookies()
    page.goto(f"{base}/login", wait_until="networkidle")
    page.evaluate("localStorage.clear()")
    page.reload(wait_until="networkidle")
    page.get_by_label("Email").fill(os.environ["HELM_E2E_EMAIL"])
    page.get_by_label("Password").fill(os.environ["HELM_E2E_PASSWORD"])
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url(f"{base}/", timeout=20000)
    failures += not step("owner login", True)
    page.get_by_role("link", name="Settings").first.click()
    page.wait_for_load_state("networkidle")
    failures += not step("owner sees MCP token form with project choices", page.get_by_text("Projects this token can see").is_visible())
    # Owner project page: the refresh button exists and is enabled, but is deliberately not clicked.
    for href in hrefs:
        if "demo" in href:
            continue
        page.goto(f"{base}{href}", wait_until="networkidle")
        if page.get_by_role("navigation", name="Project sections").count():
            page.get_by_role("navigation", name="Project sections").get_by_role("button", name="Rankings").click()
            settle(page)
            failures += not step("owner Rankings tab has Refresh now", page.get_by_role("button", name="Refresh now").count() == 1)
            break
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://helm.billtoolbox.com")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    sys.exit(run(args.base.rstrip("/"), args.headed))
