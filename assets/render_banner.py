import os, sys, subprocess

here = os.path.dirname(os.path.abspath(__file__))
html = os.path.join(here, "banner.html")
out = os.path.join(here, "banner.png")
url = "file:///" + html.replace("\\", "/")
W, H = 1280, 360


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
    print("FAILED to render banner")
    sys.exit(1)
