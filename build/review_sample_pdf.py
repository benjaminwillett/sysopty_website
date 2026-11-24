"""Confidentiality review of a PDF before it is published.

    PYTHONPATH=build/.work/pylib python build/review_sample_pdf.py <file.pdf> [--thumbs DIR]

Every page counts as published: there is no leniency for unpublished pages. Checks:
  * structure: no JavaScript, launch or open actions, forms, embedded files, external links;
  * metadata and bookmarks: listed in full (they are synthetic or generic), scanned like text;
  * text of every page and every decompressed stream: workstation paths, user and account
    names, e-mail addresses, URLs, non-synthetic domains, the carrier name (P-02);
  * comparison with the real customer identifiers on this machine (the file SYSOPTY_PRIVATE_RULES names),
    as in make_synthetic_assets --stage check; matches print as salted hashes only.
--thumbs renders every page for the visual review.
Exit status 1 on any failure.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SYNTHETIC_DOMAINS = ("riverside.example", "example.com", "example.net", "example.org")
PATTERNS = {
    "workstation path": r"(?i)\b[a-z]:\\|\\users\\|/users/|appdata|sysoptysitebuild|desktop[\\/]tools",
    "e-mail address": r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",
    "URL": r"(?i)\b(?:https?|ftp|file)://[^\s)>\]]+",
}


# Compared by digest, so this repository does not name the carrier. "examplecarrier" is the synthetic entry its test uses.
CARRIER_DIGESTS = {
    "22af2aa4a590cfcb23a7b3f130863426182978b74e64e9d173cb176a4b793116",
    "33dd2eb2b0136caba4d64c86e3a48c2c6ef4981ab9096134af56e028cb31863e",
}


def carrier_words(text: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if hashlib.sha256(w.encode()).hexdigest() in CARRIER_DIGESTS]


def reviewer_patterns() -> dict:
    """The account running this review, plus any reviewer-specific terms: a JSON object of {kind: regex} in the file
    SYSOPTY_REVIEW_TERMS names, kept outside this repository."""
    out = {"account name": rf"(?i)\b{re.escape(getpass.getuser())}\b"}
    path = os.environ.get("SYSOPTY_REVIEW_TERMS")
    if path:
        out.update(json.loads(Path(path).read_text(encoding="utf-8")))
    return out


PATTERNS.update(reviewer_patterns())
STRUCTURE = {
    "JavaScript": rb"/JavaScript|/JS\b", "launch action": rb"/Launch\b", "open action (other than a page view)": rb"/OpenAction(?!\s*\[\s*\d+ 0 R\s*/Fit)",
    "additional actions": rb"/AA\b", "form": rb"/AcroForm\b", "embedded file": rb"/EmbeddedFile|/FileAttachment",
    "external link": rb"/URI\b", "remote go-to": rb"/GoToR\b", "submit/import": rb"/SubmitForm|/ImportData",
}


def _streams(raw: bytes):
    """Decompressed streams that can carry text: page content, XMP metadata, object streams.
    Image and embedded-font data are skipped (no text, and megabytes of noise)."""
    for m in re.finditer(rb"(?<!end)stream\r?\n", raw):
        end = raw.find(b"endstream", m.end())
        if end < 0:
            continue
        head = raw[max(0, raw.rfind(b"<<", 0, m.start()) - 200):m.start()]
        if re.search(rb"/Subtype\s*/Image|/Length1\b|/FontFile|/SMask", head):
            continue
        try:
            yield zlib.decompress(raw[m.end():end])
        except zlib.error:
            data = raw[m.end():end]
            if sum(32 <= c < 127 or c in (9, 10, 13) for c in data) >= 0.95 * len(data):
                yield data                                    # uncompressed text, e.g. XMP


# The neutral evidence root the synthetic reports are generated from (engine.evidence_drive).
EVIDENCE_ROOT = "R:\\artifacts\\Riverside Technology Group"


def _allowed(kind: str, value: str, rest: str = "") -> bool:
    if kind == "workstation path":
        return rest.startswith(EVIDENCE_ROOT)
    if kind == "e-mail address":
        return value.lower().split("@", 1)[1].endswith(SYNTHETIC_DOMAINS)
    if kind == "URL":
        host = re.sub(r"(?i)^[a-z]+://", "", value).split("/", 1)[0].lower()
        return host.endswith(SYNTHETIC_DOMAINS)
    return False


def review(path: Path, thumbs: Path | None = None) -> int:
    import pypdfium2 as pdfium
    raw = path.read_bytes()
    pdf = pdfium.PdfDocument(str(path))
    failures, notes = [], []
    print(f"file: {path.name}  {len(raw):,} bytes  sha256 {hashlib.sha256(raw).hexdigest()}  pages {len(pdf)}")

    dicts = re.sub(rb"(?<!end)stream\r?\n.*?endstream", b"", raw, flags=re.S)        # object dictionaries only
    for kind, pat in STRUCTURE.items():
        n = len(re.findall(pat, dicts))
        (failures if n else notes).append(f"structure: {kind}: {n}")
    n_att = pdf.count_attachments()
    (failures if n_att else notes).append(f"structure: attachments (pdfium): {n_att}")

    meta = pdf.get_metadata_dict()
    print("metadata:", {k: v for k, v in meta.items() if v})
    toc = [(b.level, b.get_title()) for b in pdf.get_toc()]
    print(f"bookmarks: {len(toc)}")
    for level, title in toc:
        print("  " * level + "- " + title)

    sources = {"metadata": "\n".join(f"{k}: {v}" for k, v in meta.items()),
               "bookmarks": "\n".join(t for _, t in toc)}
    for i in range(len(pdf)):
        page = pdf[i]
        sources[f"page {i + 1}"] = page.get_textpage().get_text_bounded()
        annots = pdfium.raw.FPDFPage_GetAnnotCount(page.raw)
        if annots:
            notes.append(f"page {i + 1}: {annots} annotation(s)")
    for j, s in enumerate(_streams(raw)):
        sources[f"stream {j}"] = s.decode("latin-1")
    print(f"scanning {len(sources)} sources, {sum(map(len, sources.values())):,} characters", flush=True)

    for name, text in sources.items():
        for kind, pat in PATTERNS.items():
            for m in re.finditer(pat, text):
                rest = re.sub(r"\s+", " ", text[m.start():m.start() + len(EVIDENCE_ROOT) + 20])  # table wrapping
                if not _allowed(kind, m.group(0), rest):
                    failures.append(f"{name}: {kind}: {m.group(0)[:60]!r}")
        if carrier_words(text):
            failures.append(f"{name}: carrier name (P-02)")

    import make_synthetic_assets as M
    real = M._real_identifiers()
    if real is None:
        failures.append("real-identifier comparison could not run: private comparison data not on this machine")
    else:
        hits = set()
        for name, text in sources.items():
            low = text.lower()
            compact = re.sub(r"[:.\-]", "", low)
            for w in real["blocked"]:
                if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                    hits.add((name, "blocked word", w))
            for kind, values, hay in (("real device name", real["names"], low), ("real serial", real["serials"], low),
                                      ("real MAC", real["macs"], compact)):
                hits |= {(name, kind, v) for v in values if v in hay}
            for ip in set(re.findall(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])", text)) & real["ips"]:
                hits.add((name, "real IP", ip))
        for name, kind, value in sorted(hits):
            tag = "#" + hashlib.sha256(real["salt"].encode() + value.encode()).hexdigest()[:10]
            if kind == "real IP" and (value.endswith(".0") or value == "10.0.0.0"):
                notes.append(f"{name}: network address shared with a real range (not a host) {tag}")
            else:
                failures.append(f"{name}: {kind} {tag}")
        notes.append(f"compared {len(sources)} sources with {len(real['names'])} names, {len(real['serials'])} serials, "
                     f"{len(real['macs'])} MACs, {len(real['ips'])} IPs, {len(real['blocked'])} words")

    if thumbs:
        thumbs.mkdir(parents=True, exist_ok=True)
        for i in range(len(pdf)):
            pdf[i].render(scale=1.1).to_pil().convert("RGB").save(thumbs / f"p{i + 1:03d}.png")
        notes.append(f"rendered {len(pdf)} pages to {thumbs.name}/")

    for n in notes:
        print("ok:", n)
    for f in failures:
        print("FAIL:", f)
    print(f"{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--thumbs", type=Path)
    a = ap.parse_args()
    raise SystemExit(review(a.pdf, a.thumbs))
