"""Render slides."""

import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "post_template.html")


def build(c):
    slides = ([{"type": "cover", "hook": c["hook"], "sticker": c.get("cover_sticker")}]
              + c["slides"] + [{"type": "about"}])
    assert len(slides) == 10, f'{c["id"]}: expected 8 middle slides, got {len(c["slides"])}'
    return {**c, "slides": slides}


async def _render(c, out_root):
    c = build(c)
    od = os.path.join(out_root, c["id"])
    os.makedirs(od, exist_ok=True)
    warn = []
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1080})
        await pg.goto("file://" + TEMPLATE)
        await pg.evaluate("document.fonts.ready.then(() => true)")
        await pg.wait_for_timeout(600)
        for i in range(10):
            r = await pg.evaluate("([P,i]) => window.renderSlide(P,i)", [c, i])
            if i == 0 and r["scale"] < 0.85:
                warn.append(f"cover hook too long (font {r['scale']:.0%}): write a shorter hook "
                            f"(<= 40 chars, short words, [[1 short word]])")
            elif r["overflow"] or r["scale"] < 0.7:
                warn.append(f"slide {i + 1}: scale {r['scale']:.2f}{' OVERFLOW' if r['overflow'] else ''}")
            await pg.screenshot(path=os.path.join(od, f"{i + 1:02d}.png"))
        await b.close()
    with open(os.path.join(od, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(c["caption"].strip() + "\n")
    return "; ".join(warn)


def render(c, out_root):
    return asyncio.run(_render(c, out_root))


if __name__ == "__main__":
    for path in sys.argv[1:]:
        c = json.load(open(path, encoding="utf-8"))
        print(c["id"], render(c, os.path.join(HERE, "out")) or "ok")
