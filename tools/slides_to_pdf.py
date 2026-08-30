"""slides.html -> slides.pdf (1 slide = 1 page, 1280px wide).

usage: python tools/slides_to_pdf.py [--out slides.pdf] [--html slides.html]
"""
import argparse
import io
import os
import sys

from pypdf import PdfReader, PdfWriter
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDTH = 1280
BASE_HEIGHT = 800

PRINT_CSS = """
#bar,#prog{display:none !important}
html,body{overflow:visible !important}
.slide{overflow:visible !important}
"""


def measure(page, idx):
    return page.evaluate(
        """(i) => {
            const ss = document.querySelectorAll('.slide');
            ss.forEach(s => s.classList.remove('on'));
            const el = ss[i];
            el.classList.add('on');
            el.scrollTop = 0;
            return Math.ceil(Math.max(el.scrollHeight, el.getBoundingClientRect().height));
        }""",
        idx,
    )


def set_height(page, h):
    page.evaluate(
        """(h) => {
            document.documentElement.style.height = h + 'px';
            document.body.style.height = h + 'px';
            const d = document.getElementById('deck');
            d.style.position = 'absolute';
            d.style.top = '0'; d.style.left = '0';
            d.style.width = '100%';
            d.style.height = h + 'px';
        }""",
        h,
    )


def overflow_of(page, idx):
    return page.evaluate(
        """(i) => {
            const el = document.querySelectorAll('.slide')[i];
            return Math.ceil(el.scrollHeight - el.clientHeight);
        }""",
        idx,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=os.path.join(ROOT, "slides.html"))
    ap.add_argument("--out", default=os.path.join(ROOT, "slides.pdf"))
    args = ap.parse_args()

    html = os.path.abspath(args.html)
    url = "file:///" + html.replace("\\", "/")
    pages_bytes = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        try:
            page = browser.new_page(viewport={"width": WIDTH, "height": BASE_HEIGHT})
            page.goto(url, wait_until="load")
            page.add_style_tag(content=PRINT_CSS)
            page.emulate_media(media="screen")
            try:
                page.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
            except Exception:
                print("warn: web fonts not loaded, using fallback", file=sys.stderr)
            page.wait_for_function(
                "Array.from(document.images).every(im => im.complete && im.naturalWidth > 0)",
                timeout=30000,
            )
            total = page.evaluate("document.querySelectorAll('.slide').length")

            for i in range(total):
                set_height(page, BASE_HEIGHT)
                h = max(BASE_HEIGHT, measure(page, i))
                for _ in range(4):
                    set_height(page, h)
                    page.evaluate("() => new Promise(r => requestAnimationFrame(() => r()))")
                    over = overflow_of(page, i)
                    if over <= 0:
                        break
                    h += over + 8
                pdf = page.pdf(
                    width=f"{WIDTH}px",
                    height=f"{h}px",
                    print_background=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                    page_ranges="1",
                )
                pages_bytes.append(pdf)
                print(f"slide {i + 1}/{total}: {WIDTH}x{h}px, {len(pdf) // 1024}KB")
        finally:
            browser.close()

    writer = PdfWriter()
    for b in pages_bytes:
        writer.append(PdfReader(io.BytesIO(b)))
    tmp = args.out + ".tmp"
    with open(tmp, "wb") as f:
        writer.write(f)
    os.replace(tmp, args.out)
    n = len(PdfReader(args.out).pages)
    size = os.path.getsize(args.out)
    print(f"wrote {args.out}: {n} pages, {size / 1024 / 1024:.2f} MB")
    if n != len(pages_bytes):
        sys.exit(f"page count mismatch: {n} != {len(pages_bytes)}")


if __name__ == "__main__":
    main()
