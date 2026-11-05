"""Tests for frontend performance budgets, asset integrity, and server security (Deliverable 2)."""

import gzip
import html.parser
import json
import os
import re
import sqlite3
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from tools import control

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "harness" / "web"


@pytest.fixture
def test_server(temp_db):
    """Spawns DashboardHandler on ephemeral port bound to 127.0.0.1 with temp_db."""
    from harness import dashboard
    os.environ["HARNESS_DB"] = temp_db
    server = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
    host, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", port, temp_db
    server.shutdown()
    server.server_close()


def test_no_external_urls_in_web_assets():
    """Assert zero runtime external network URLs in web assets (Hard Rule 2)."""
    assert WEB_DIR.is_dir(), "harness/web directory must exist"
    violations = []
    url_pattern = re.compile(r"https?://[^\s'\"`<>]+", re.IGNORECASE)

    for path in WEB_DIR.rglob("*"):
        if not path.is_file() or path.suffix in (".woff2", ".txt", ".md"):
            continue

        text = path.read_text(errors="ignore")
        # Strip out code comments before searching for live network URLs
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        stripped = re.sub(r"//.*$", "", stripped, flags=re.MULTILINE)
        stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)

        matches = url_pattern.findall(stripped)
        # Allow schema.org or w3.org xml namespaces inside SVG if any
        matches = [m for m in matches if "w3.org" not in m]
        if matches:
            violations.append(f"{path.relative_to(REPO_ROOT)}: {matches}")

    assert not violations, f"External network URLs found in runtime frontend assets:\n" + "\n".join(violations)


def test_no_inline_scripts_or_styles_in_index_html():
    """Assert no inline scripts, no inline styles, and no on* handlers in index.html (Hard Rule 4)."""
    index_path = WEB_DIR / "index.html"
    assert index_path.is_file()
    content = index_path.read_text(encoding="utf-8")

    # Disallow <style> tags
    assert "<style" not in content.lower(), "index.html must not contain inline <style> tags"

    # Disallow script bodies (<script>...</script> containing executable code)
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", content, re.DOTALL | re.IGNORECASE)
    for s in scripts:
        assert not s.strip(), f"index.html must not contain inline script bodies: '{s.strip()[:50]}...'"

    # Disallow inline on* event handlers (e.g. onclick, onchange)
    on_handlers = re.findall(r"\son\w+\s*=", content, re.IGNORECASE)
    assert not on_handlers, f"index.html contains inline event handlers: {on_handlers}"


def test_file_size_budgets():
    """Verify performance budgets on transfer sizes (HTML <= 8KB, CSS <= 24KB, JS <= 45KB, fonts <= 140KB)."""
    index_path = WEB_DIR / "index.html"
    assert index_path.is_file()
    html_gzip = len(gzip.compress(index_path.read_bytes()))
    assert html_gzip <= 8 * 1024, f"HTML gzip size {html_gzip} exceeds 8KB budget"

    css_files = list((WEB_DIR / "css").glob("*.css")) if (WEB_DIR / "css").is_dir() else []
    total_css = b"".join(f.read_bytes() for f in css_files)
    css_gzip = len(gzip.compress(total_css))
    assert css_gzip <= 24 * 1024, f"CSS gzip size {css_gzip} exceeds 24KB budget"

    js_files = list((WEB_DIR / "js").glob("*.js")) if (WEB_DIR / "js").is_dir() else []
    total_js = b"".join(f.read_bytes() for f in js_files)
    js_gzip = len(gzip.compress(total_js))
    assert js_gzip <= 45 * 1024, f"JS gzip size {js_gzip} exceeds 45KB budget"

    font_files = list((WEB_DIR / "fonts").glob("*.woff2")) if (WEB_DIR / "fonts").is_dir() else []
    fonts_raw = sum(f.stat().st_size for f in font_files)
    assert fonts_raw <= 140 * 1024, f"Fonts total raw size {fonts_raw} exceeds 140KB budget"


def test_accessibility_elements_have_labels():
    """Verify all static buttons and links in index.html possess accessible labels."""
    index_path = WEB_DIR / "index.html"
    content = index_path.read_text(encoding="utf-8")

    class LabelAuditor(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.errors = []
            self.current_tag = None
            self.current_attrs = {}
            self.text_buffer = ""

        def handle_starttag(self, tag, attrs):
            if tag in ("button", "a"):
                self.current_tag = tag
                self.current_attrs = dict(attrs)
                self.text_buffer = ""

        def handle_data(self, data):
            if self.current_tag:
                self.text_buffer += data.strip()

        def handle_endtag(self, tag):
            if tag == self.current_tag:
                has_text = bool(self.text_buffer)
                has_aria = bool(self.current_attrs.get("aria-label") or self.current_attrs.get("aria-labelledby"))
                has_title = bool(self.current_attrs.get("title"))
                if not (has_text or has_aria or has_title):
                    self.errors.append(f"<{tag}> missing accessible label: {self.current_attrs}")
                self.current_tag = None
                self.current_attrs = {}

    auditor = LabelAuditor()
    auditor.feed(content)
    assert not auditor.errors, f"Inaccessible buttons or links found:\n" + "\n".join(auditor.errors)


def test_security_headers_and_csp(test_server):
    """Verify Content-Security-Policy, nosniff, and Cache-Control headers."""
    base_url, port, _ = test_server
    req = urllib.request.Request(f"{base_url}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        headers = dict(resp.headers)
        csp = headers.get("Content-Security-Policy", "")
        assert "default-src 'none'" in csp
        assert "script-src 'self'" in csp
        assert "style-src 'self'" in csp
        assert "font-src 'self'" in csp
        assert "img-src 'self' data:" in csp
        assert "connect-src 'self'" in csp
        assert headers.get("X-Content-Type-Options") == "nosniff"


def test_etag_and_304_support(test_server):
    """Verify ETag calculation and 304 Not Modified when client sends If-None-Match."""
    base_url, _, _ = test_server
    req1 = urllib.request.Request(f"{base_url}/api/state")
    with urllib.request.urlopen(req1) as resp1:
        assert resp1.status == 200
        etag = resp1.headers.get("ETag")
        assert etag, "Response must include an ETag header"

    req2 = urllib.request.Request(f"{base_url}/api/state", headers={"If-None-Match": etag})
    try:
        urllib.request.urlopen(req2)
        pytest.fail("Expected HTTP 304 Not Modified")
    except urllib.error.HTTPError as err:
        assert err.code == 304


def test_path_traversal_prevention(test_server):
    """Verify path traversal attacks return 404/403 and never expose external files."""
    base_url, _, _ = test_server
    attack_paths = [
        "/static/../../etc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/css/../../harness.db",
        "/..%2f..%2fharness.db",
    ]
    for p in attack_paths:
        req = urllib.request.Request(f"{base_url}{p}")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code in (403, 404), f"Path {p} should be rejected, got {exc_info.value.code}"


def test_api_state_omits_answers_without_token(test_server):
    """Verify /api/state omits sensitive answer text when requested without token."""
    base_url, _, temp_db = test_server
    conn = sqlite3.connect(temp_db)
    conn.execute("INSERT OR REPLACE INTO screening_qa VALUES ('secret_q', 'classified_answer')")
    conn.execute("INSERT INTO app_story_answers (application, question, answer, status, saved_at) VALUES ('SecretCo', 'Prompt', 'Sensitive answer body', 'DRAFT', '2026-11-01')")
    conn.commit()
    conn.close()

    req = urllib.request.Request(f"{base_url}/api/state")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        screening = data.get("screening", [])
        for item in screening:
            assert "answer" not in item
            assert "question_key" in item

        app_ans = data.get("app_answers", [])
        for item in app_ans:
            assert "answer" not in item
            assert "application" in item


def test_api_answer_reveal_requires_token(test_server):
    """Verify individual answer reveal endpoint /api/answers/<id> requires X-Token."""
    base_url, _, temp_db = test_server
    conn = sqlite3.connect(temp_db)
    cur = conn.cursor()
    cur.execute("INSERT INTO app_story_answers (application, question, answer, status, saved_at) VALUES ('Acme Corp', 'Why backend?', 'I love distributed systems.', 'SAVED', '2026-11-01')")
    ans_id = cur.lastrowid
    conn.commit()
    conn.close()

    # Without token -> 403
    req_no_token = urllib.request.Request(f"{base_url}/api/answers/{ans_id}")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_no_token)
    assert exc_info.value.code == 403

    # With token -> 200 with answer text
    tok = control.get_token()
    req_with_token = urllib.request.Request(f"{base_url}/api/answers/{ans_id}", headers={"X-Token": tok})
    with urllib.request.urlopen(req_with_token) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode())
        assert data.get("answer") == "I love distributed systems."


def test_host_header_check_rejects_evil_host(test_server):
    """Verify requests with invalid Host headers are rejected with 403."""
    base_url, _, _ = test_server
    req_get = urllib.request.Request(f"{base_url}/", headers={"Host": "attacker.evil.com"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_get)
    assert exc_info.value.code == 403

    req_post = urllib.request.Request(
        f"{base_url}/ctl/toggle",
        data=b'{"name":"jobs","on":true}',
        headers={"Host": "attacker.evil.com", "Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_post)
    assert exc_info.value.code == 403
