"""Photograph every screen, so the design can be looked at instead of imagined.

    python tools/shots.py            # all screens, 1440 wide
    python tools/shots.py queue      # just one
    python tools/shots.py --width 390

Writes PNGs to .shots/, which is ignored. Needs the server already running on
:8000 -- it is a camera, not a test harness, and it deliberately does not
start or seed anything so that what it photographs is what the founder sees.

It pointed at :7500 while the product serves 8000 everywhere (``server.py``,
``__main__.py``, the README), so run as documented it printed eight
``net::ERR_CONNECTION_REFUSED`` lines and exited 0 -- a camera that
photographs nothing and reports success. A screen that could not be
photographed now fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

#: The port the product actually serves on. Overridable, because a founder
#: with two workspaces open runs the second somewhere else.
BASE = os.environ.get("VINZOR_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parent.parent / ".shots"

#: name -> what to click, in order, to arrive there from a signed-in queue.
SCREENS = {
    "queue": [],
    "queue-open": [".group .head"],
    # Groups start collapsed, so a file has to be uncovered before it can be
    # opened -- the same two clicks the officer makes.
    "case": [".group .head", ".open-file"],
    "party": [".group .head", ".open-file", ".case-about .as-link"],
    # The check runs live against the local index; the verdict can take a few
    # seconds to arrive, so this screen waits for it rather than for a pause.
    "check": [".group .head", ".open-file", ".case-about .as-link", "#check"],
    "regulatory": ["#regulatory"],
    "screening": ["#screening"],
    "finder": ["#find"],
}


def shoot(page, name: str, steps, full: bool) -> None:
    page.goto(BASE, wait_until="networkidle")

    # Sign in as the AML officer if the picker is showing.
    picker = page.locator(".signin button").first
    if picker.count():
        picker.click()
        page.wait_for_selector(".greeting", timeout=10_000)

    for step in steps:
        target = page.locator(step).filter(visible=True).first
        target.wait_for(state="visible", timeout=10_000)
        target.click()
        page.wait_for_timeout(1000)

    if name == "check":
        page.wait_for_selector(".inv-verdict", timeout=90_000)
    page.wait_for_timeout(400)
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=full)
    print(f"  {path.relative_to(OUT.parent)}")


def main(argv) -> int:
    width = 1440
    if "--width" in argv:
        width = int(argv[argv.index("--width") + 1])
        argv = [a for i, a in enumerate(argv)
                if i not in (argv.index("--width"), argv.index("--width") + 1)]
    full = "--full" in argv
    wanted = [a for a in argv if not a.startswith("--")] or list(SCREENS)

    OUT.mkdir(exist_ok=True)
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900},
                                device_scale_factor=2)
        went_wrong = []
        for name in wanted:
            if name not in SCREENS:
                print(f"  no screen called {name!r}; known: {', '.join(SCREENS)}")
                went_wrong.append(name)
                continue
            try:
                shoot(page, name, SCREENS[name], full)
            except Exception as problem:
                print(f"  {name}: {problem}")
                went_wrong.append(name)
        browser.close()
    if went_wrong:
        print()
        print(f"  {len(went_wrong)} of {len(wanted)} screens were not "
              f"photographed: {', '.join(went_wrong)}")
        print(f"  Is the server running at {BASE}?")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
