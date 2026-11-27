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
            issues = await pg.evaluate("() => window.checkLayout()")
            if i == 0 and any(".stk" in x for x in issues):  # cover sticker hits the hook: drop the sticker
                c["slides"][0]["nostk"] = True
                r = await pg.evaluate("([P,i]) => window.renderSlide(P,i)", [c, i])
                issues = await pg.evaluate("() => window.checkLayout()")
                print(f"  cover: sticker removed (it overlapped the hook){' - still: ' + '; '.join(issues) if issues else ''}", flush=True)
            for fix in (("note", "who"), "trim"):
                if not issues or i in (0, 9):
                    break
                sl = c["slides"][i]
                if fix == "trim":
                    for k in ("points", "rows"):
                        if isinstance(sl.get(k), list) and len(sl[k]) > 3:
                            sl[k] = sl[k][:3]
                else:
                    for k in fix:
                        sl.pop(k, None)
                r = await pg.evaluate("([P,i]) => window.renderSlide(P,i)", [c, i])
                issues = await pg.evaluate("() => window.checkLayout()")
                print(f"  slide {i + 1}: layout fixed by {fix if fix == 'trim' else 'dropping the note'}"
                      f"{' (still: ' + '; '.join(issues) + ')' if issues else ''}", flush=True)
            if issues:
                warn.append(f"slide {i + 1}: " + "; ".join(issues) + " - shorten this slide")
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
