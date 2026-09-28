"""Tests run against a local HTTP server: no internet needed."""
import http.server
import threading

import pytest

import site_audit

GOOD = """<!doctype html><html><head><title>Riverside Salon | Hair in Miramichi</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Cuts and colour."></head>
<body><a href="tel:+15065550100">Call</a><a href="/book">Book now</a>
<footer>&copy; 2026 Riverside Salon</footer>""" + "<p>content</p>" * 400 + "</body></html>"

OLD = """<html><head><title>Home</title></head><body><table><tr><td>Welcome!</td></tr></table>
<script src="jquery-1.4.2.min.js"></script><p>Copyright 2012 Studio</p>""" + "<p>x</p>" * 800 + "</body></html>"

PARKED_JS = '<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="/lander"}</script></head></html>'
SPAM = "<html><head><title>x</title></head><body>" + "slot gacor situs slot casino online " * 5 + "</body></html>"

PAGES = {"/good": (200, GOOD), "/old": (200, OLD), "/parked": (200, PARKED_JS), "/spam": (200, SPAM),
         "/missing": (404, "<html><title>Not found</title></html>")}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        code, body = PAGES.get(self.path, (404, "nope"))
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_good_site_only_loses_points_for_http(base):
    r = site_audit.audit(base + "/good", this_year=2026)
    assert r.status == "ok"
    assert r.problems == ["no HTTPS: browsers label it 'Not secure'"]
    assert r.score == 3


def test_old_site_collects_the_expected_problems(base):
    r = site_audit.audit(base + "/old", this_year=2026)
    text = " | ".join(r.problems)
    assert "not mobile-friendly" in text
    assert "copyright 2012: looks abandoned" in text
    assert "old jQuery 1.4" in text
    assert "no useful page title" in text
    assert "no contact form or online booking" in text
    assert r.copyright_year == 2012
    assert r.score > site_audit.audit(base + "/good", this_year=2026).score


def test_javascript_parking_redirect_is_detected(base):
    r = site_audit.audit(base + "/parked")
    assert any("expired or parked domain" in p for p in r.problems)
    assert not any("almost empty page" in p for p in r.problems)
    assert r.score >= 10


def test_spam_takeover_is_detected(base):
    r = site_audit.audit(base + "/spam")
    assert any("spam" in p for p in r.problems)


def test_http_error_is_reported(base):
    r = site_audit.audit(base + "/missing")
    assert r.status == "error"
    assert "returns HTTP 404" in r.problems


def test_unresolvable_domain_is_down():
    r = site_audit.audit("http://this-domain-does-not-exist.invalid", timeout=5)
    assert r.status == "down"
    assert r.score >= 9


def test_read_urls_from_csv_dedupes_and_skips_blanks(tmp_path):
    f = tmp_path / "leads.csv"
    f.write_text("name,website\nA,example.com\nB,\nC,http://example.com/\nD,other.org\n", encoding="utf-8")
    assert site_audit.read_urls(str(f), None) == ["example.com", "other.org"]


def test_read_urls_csv_without_url_column_fails(tmp_path):
    f = tmp_path / "leads.csv"
    f.write_text("name,phone\nA,1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        site_audit.read_urls(str(f), None)


def test_reports_are_sorted_worst_first(base, tmp_path):
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{base}/good\n# comment\n{base}/parked\n{base}/old\n", encoding="utf-8")
    out_csv, out_md = tmp_path / "r.csv", tmp_path / "r.md"
    assert site_audit.main([str(urls), "--csv", str(out_csv), "--md", str(out_md), "--workers", "2"]) == 0
    rows = out_csv.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 4
    scores = [int(line.split(",")[0]) for line in rows[1:]]
    assert scores == sorted(scores, reverse=True)
    assert "/parked" in rows[1]
    assert out_md.read_text(encoding="utf-8").startswith("# Website health report")
