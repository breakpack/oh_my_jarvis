"""Playwright-backed browser runtime (SPEC.md §10 Browser Mode:
deterministic workflow path).

Every session launches a fresh headless Chromium instance with a brand
new browser context — no persisted cookies, storage state, or login
session is ever reused across sessions. SPEC §10 requires that login
session reuse only happen with explicit per-connection permission; since
there's no Connections/OAuth system yet (a later phase), the only safe
default is "always start logged out," and a fresh context guarantees that
by construction rather than by a policy check that could be forgotten.
"""

from __future__ import annotations

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

DEFAULT_NAVIGATE_TIMEOUT_MS = 15000


class PlaywrightSession:
    """Async context manager: one headless Chromium browser + one fresh,
    unauthenticated BrowserContext, torn down on exit."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> PlaywrightSession:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        # A brand-new context per session: no persisted cookies/storage
        # state, i.e. always a logged-out session (SPEC §10 "세션과 연결 분리").
        self._context = await self._browser.new_context()
        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError(
                "PlaywrightSession is not open — use 'async with PlaywrightSession() as session'."
            )
        return self._page

    async def navigate(self, url: str, timeout: int = DEFAULT_NAVIGATE_TIMEOUT_MS) -> str:
        """Navigate to `url` and return the resulting page title."""
        await self.page.goto(url, timeout=timeout)
        return await self.page.title()

    async def get_text(self, selector: str | None = None) -> str:
        """Return the rendered inner text of `selector` (default: the whole body)."""
        return await self.page.inner_text(selector or "body")

    async def fill(self, selector: str, value: str) -> None:
        await self.page.fill(selector, value)

    async def click(self, selector: str) -> None:
        await self.page.click(selector)
