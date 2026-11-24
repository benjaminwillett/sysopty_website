"""The published sample report and the findings showcase."""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))
import package_release  # noqa: E402
import server  # noqa: E402

PUBLIC = ROOT / "public"
PAGE = (PUBLIC / "index.html").read_text(encoding="utf-8")


def client():
    return server.create_app({"FORM_SECRET": "test-secret", "SENDER": [].append}).test_client()


def test_no_document_is_published():
    docs = [p.relative_to(ROOT).as_posix() for p in PUBLIC.rglob("*")
            if p.is_file() and p.suffix.lower() not in package_release.ALLOWED_PUBLIC]
    assert docs == [] and package_release.APPROVED_DOCUMENTS == {}


@pytest.mark.parametrize("path", ["/samples/other.pdf", "/samples/sysopty_sample_network_as-built_report.PDF",
                                  "/img/x.pdf", "/samples/Sysopty_Sample_Network_As-Built_Report.pdf"])
def test_no_pdf_path_is_served(path):
    assert client().get(path).status_code == 404


def test_findings_showcase():
    i = PAGE.index('id="findings"')
    block = PAGE[i:PAGE.index("</section>", i)]
    assert "More than an inventory. Findings with their evidence." in block
    for title in ("For engineers: a prioritised list", "For reviewers: one current record",
                  "Between refreshes: what changed"):
        assert f"<h3>{title}</h3>" in block
    assert "illustrative" in block and "fictional" in block  # the example finding is not from a real network
    assert "should be reviewed by your engineers before any change is made" in block   # qualified, not overstated


def test_no_tracking_and_no_document_links():
    assert not re.search(r"(?i)google-analytics|googletagmanager|gtag\(|plausible|matomo|segment\.com|hotjar", PAGE)
    assert "onclick" not in PAGE
    assert "/samples/" not in PAGE and ".pdf" not in PAGE.lower() and "/demo/" not in PAGE
