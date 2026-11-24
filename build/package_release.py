"""Builds the deployment archive from an allowlist, so nothing private can ship.

    python build/package_release.py [--out dist]

The archive holds server.py, wsgi.py, requirements.txt and public/ only. It refuses to
build if a forbidden file would be included, and writes a SHA-256 manifest beside it.
The only document allowed is the reviewed sample report, and only with the exact bytes that
passed the confidentiality review: a regenerated PDF must be
reviewed again and its hash updated here before it can ship.
build/ (private rules, asset tooling), tests/, docs and .env files are never packaged.
"""
from __future__ import annotations

import argparse
import hashlib
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_FILES = ("server.py", "wsgi.py", "requirements.txt")
INCLUDE_DIRS = ("public",)
ALLOWED_PUBLIC = {".html", ".css", ".js", ".webp", ".png", ".svg", ".ico", ".woff2", ".txt", ".xml"}
FORBIDDEN_NAMES = {"private_rules.json", ".env", "manifest.json"}
FORBIDDEN_SUFFIXES = {".pdf", ".xlsx", ".json", ".dot", ".py", ".pyc", ".log", ".zip"}
# public/ path -> SHA-256 of the reviewed file.
APPROVED_DOCUMENTS: dict[str, str] = {}   # none published: Sysopty has no downloadable document yet


def collect() -> list[Path]:
    files = [ROOT / f for f in INCLUDE_FILES]
    for d in INCLUDE_DIRS:
        files += sorted(p for p in (ROOT / d).rglob("*") if p.is_file())
    problems = []
    for p in files:
        rel = p.relative_to(ROOT)
        if not p.is_file():
            problems.append(f"missing: {rel}")
        elif p.name in FORBIDDEN_NAMES or p.name.startswith("."):
            problems.append(f"forbidden file: {rel}")
        elif rel.as_posix() in APPROVED_DOCUMENTS:
            if hashlib.sha256(p.read_bytes()).hexdigest() != APPROVED_DOCUMENTS[rel.as_posix()]:
                problems.append(f"document differs from the reviewed version: {rel}")
        elif rel.parts[0] == "public" and (p.suffix.lower() not in ALLOWED_PUBLIC or p.suffix.lower() in FORBIDDEN_SUFFIXES):
            problems.append(f"not a web asset: {rel}")
    if problems:
        raise SystemExit("refusing to package:\n  " + "\n  ".join(problems))
    return files


def build(out: Path) -> Path:
    files = collect()
    out.mkdir(parents=True, exist_ok=True)
    name = f"sysopty-site-{time.strftime('%Y%m%d-%H%M%S')}"
    archive = out / f"{name}.zip"
    lines = []
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            rel = p.relative_to(ROOT).as_posix()
            z.write(p, rel)
            lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}")
    (out / f"{name}.sha256").write_text(
        "\n".join(lines) + f"\n{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
    return archive


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "dist")
    a = ap.parse_args()
    path = build(a.out)
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")
