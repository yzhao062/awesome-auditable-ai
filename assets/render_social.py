"""Render the 1280x640 GitHub social-preview card from social-card.html.

GitHub's social preview slot wants a 2:1 image (1280x640 recommended). The main
banner is 32:9, so it cannot be center-cropped into that slot without losing the
composition; this renders a dedicated card instead. Upload the result under
Settings, General, Social preview.
"""

import os, sys, subprocess

here = os.path.dirname(os.path.abspath(__file__))
html = os.path.join(here, "social-card.html")
out = os.path.join(here, "social-card.png")
url = "file:///" + html.replace("\\", "/")
W, H = 640, 320  # rendered at device_scale_factor 2 -> 1280x640


def try_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("playwright import failed:", e)
        return False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
            pg.goto(url)
            pg.wait_for_timeout(350)
            pg.screenshot(path=out, clip={"x": 0, "y": 0, "width": W, "height": H})
            b.close()
        print("captured via playwright")
        return os.path.exists(out)
    except Exception as e:
        print("playwright launch/screenshot failed:", e)
        return False


def find_browser():
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def try_browser():
    b = find_browser()
    if not b:
        print("no edge/chrome found")
        return False
    cmd = [
        b, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--screenshot=" + out, "--window-size=%d,%d" % (W, H),
        "--force-device-scale-factor=2", url,
    ]
    try:
        subprocess.run(cmd, check=True, timeout=120)
        print("captured via", b)
        return os.path.exists(out)
    except Exception as e:
        print("browser screenshot failed:", e)
        return False


ok = try_playwright() or try_browser()
if ok and os.path.exists(out):
    print("OK", out, os.path.getsize(out), "bytes")
else:
    print("FAILED to render social card")
    sys.exit(1)
