"""Turns Sysopty report output into website images: figures extracted at native resolution
with their real captions, report pages rendered, WebP renditions, and the gallery markup
in public/index.html (between the gallery:start/end markers)."""
from __future__ import annotations

import re
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"
sys.path.insert(0, str(HERE / ".work" / "pylib"))

# Card crops: very wide or tall figures are cropped to a legible part; the rest fit whole.
FIT = {}          # every gallery image is cropped to its card's shape, so none needs object-fit: cover


def open_pdf(path):
    import pypdfium2 as pdfium
    return pdfium.PdfDocument(str(path))


def page_texts(pdf):
    return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r", " ")).strip()


def find(texts, pattern, used: set | None = None):
    """(page index, matching line) for the first report line matching pattern (contents pages skipped)."""
    for i, t in enumerate(texts):
        for line in re.split(r"[\r\n]+", t):
            if "...." in line:
                continue
            m = re.search(pattern, clean(line))
            if m:
                if used is not None:
                    used.add(i)
                return i, m.group(0)
    raise SystemExit(f"not in the report: {pattern}")


def caption_text(caption: str) -> str:
    """The report's caption without the evidence snapshot id and tile position."""
    return re.sub(r"\s*\((?:evidence )?snapshot [^)]*\).*$", "", caption).strip()


def largest_image(page):
    import pypdfium2.raw as raw
    best = None
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        left, bottom, right, top = obj.get_bounds()
        area = (right - left) * (top - bottom)
        if best is None or area > best[0]:
            best = (area, obj)
    return best[1] if best else None


def image_above(page, caption: str):
    """The figure a caption belongs to: the nearest image above the caption's first line."""
    import pypdfium2.raw as raw
    tp = page.get_textpage()
    hit = tp.search(caption[:24], match_case=True).get_next()
    if not hit:
        return largest_image(page)
    caption_top = tp.get_charbox(hit[0])[3]
    best = None
    for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
        left, bottom, right, top = obj.get_bounds()
        gap = bottom - caption_top
        if gap >= -2 and (best is None or gap < best[0]):
            best = (gap, obj)
    return best[1] if best else largest_image(page)


def figure_from_pdf(pdf, texts, pattern, used):
    i, caption = find(texts, pattern, used)
    return image_above(pdf[i], caption).get_bitmap(render=False).to_pil(), caption_text(caption)


def render_page(pdf, index, width=1800, crop=None):
    page = pdf[index]
    w, h = page.get_size()
    kw = {"crop": tuple(c * h if j in (1, 3) else c for j, c in enumerate(crop))} if crop else {}
    return page.render(scale=width / w, **kw).to_pil()


def render_region(pdf, index, box, scale=4):
    """A legible region of a page: box = (left, top, right, bottom) as fractions of the page."""
    full = pdf[index].render(scale=scale).to_pil().convert("RGB")
    w, h = full.size
    left, top, right, bottom = box
    return full.crop((int(left * w), int(top * h), int(right * w), int(bottom * h)))


def section_title(page_text: str, pattern: str) -> str:
    """The heading a crop starts at, as the page prints it ("1.1  Site at a glance" -> "1.1 Site at a glance")."""
    import re as _re
    m = _re.search(pattern, page_text)
    return " ".join(m.group(0).split()) if m else ""


def save_set(img, key: str, folder: Path, widths=(800, 1400), full_max=3000):
    """WebP renditions for srcset plus a full-resolution one for the lightbox (metadata-free)."""
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    img = img.convert("RGB")
    out = {}
    for w in widths:
        im = img if img.width <= w else img.resize((w, round(img.height * w / img.width)), Image.LANCZOS)
        im.save(folder / f"{key}-{w}.webp", "WEBP", quality=86, method=6)
        out[str(w)] = im.size
    full = img if img.width <= full_max else img.resize((full_max, round(img.height * full_max / img.width)),
                                                        Image.LANCZOS)
    full.save(folder / f"{key}-full.webp", "WEBP", quality=90, method=6)
    out["full"] = full.size
    return out


def write_gallery(items: list[dict], alt_site: str):
    zoom = ('<span class="zoom-hint" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>Enlarge</span>')

    def card(item, sizes_attr):
        k, w800 = item["key"], item["sizes"]["800"]
        cls = f' class="{FIT[k]}"' if k in FIT else ""
        alt = f"{item['title']} generated by Sysopty for {alt_site}"
        return f"""<figure class="shot-card">
              <h3>{escape(item['title'])}</h3>
              <button class="shot-frame" type="button" data-lightbox="gallery" data-full="/img/gallery/{k}-full.webp" data-title="{escape(item['title'])}" data-caption="{escape(item['caption'])}">
                <img{cls} src="/img/gallery/{k}-800.webp" srcset="/img/gallery/{k}-800.webp 800w, /img/gallery/{k}-1400.webp 1400w" sizes="{sizes_attr}" alt="{escape(alt)}" width="{w800[0]}" height="{w800[1]}" loading="lazy" decoding="async">
                <span class="fig-caption">{escape(item['caption'])}</span>
                {zoom}
              </button>
              <figcaption>{escape(item['text'])}</figcaption>
            </figure>"""

    two = "(max-width: 640px) calc(100vw - 32px), (max-width: 1080px) 46vw, 590px"
    three = "(max-width: 640px) calc(100vw - 32px), (max-width: 1080px) 46vw, 390px"
    block = ("<!-- gallery:start -->\n          <div class=\"gallery-row-3\">\n            "
             + "\n            ".join(card(items[i], three) for i in (0, 2, 1))
             + "\n          </div>\n          <details class=\"more-examples\">\n"
             + "            <summary>View more samples</summary>\n"
             + "            <div class=\"gallery-row-2\">\n            "
             + "\n            ".join(card(i, two) for i in items[3:])
             + "\n            </div>\n          </details>\n          <!-- gallery:end -->")
    index = PUBLIC / "index.html"
    page = index.read_text(encoding="utf-8")
    page, n = re.subn(r"<!-- gallery:start -->.*?<!-- gallery:end -->", lambda _: block, page, flags=re.S)
    if n != 1:
        raise SystemExit("gallery markers not found in index.html")
    index.write_text(page, encoding="utf-8")
