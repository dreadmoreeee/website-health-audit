"""Audit a list of small-business websites and rank them from worst to best.

For every URL it checks what a customer (and Google) would run into: the site
is down, the domain expired or was parked, the domain now shows spam, there is
no HTTPS, the page is not mobile-friendly, the copyright is years old, it is
slow, or there is no way to call or book from a phone. Each problem adds points,
so the report is sorted by how badly the site needs work.

Usage:
    python site_audit.py urls.txt                    # print a table
    python site_audit.py urls.csv --column website --csv report.csv --md report.md

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128 Safari/537.36 site-audit")
MAX_BYTES = 3_000_000

# Pages served by registrars and site builders once a domain or plan lapses.
EXPIRED_MARKERS = ("lander_system", 'href="/lander"', 'ap:"parking"', "website expired",
                   "this site is not available", "domain has expired", "this domain has expired")
PARKED_MARKERS = ("domain is for sale", "buy this domain", "this domain may be for sale", "sedoparking",
                  "hugedomains", "account suspended", "future home of", "is parked", "domain parking")
CONSTRUCTION_MARKERS = ("under construction", "coming soon", "default web site page", "index of /")
# Words that show up when an abandoned domain is taken over by spam sites.
SPAM_RE = re.compile(r"slot gacor|slot online|situs slot|judi online|togel|casino online|sbobet|"
                     r"toto macau|replica watches|payday loan|viagra|cialis", re.I)
BUILDERS = (("wix.com", "Wix"), ("wixsite", "Wix"), ("weebly", "Weebly"), ("squarespace", "Squarespace"),
            ("godaddy", "GoDaddy"), ("websitebuilder", "GoDaddy"), ("wp-content", "WordPress"),
            ("shopify", "Shopify"), ("jimdo", "Jimdo"), ("yola", "Yola"), ("joomla", "Joomla"),
            ("duda", "Duda"), ("site123", "Site123"))
BOOKING_RE = re.compile(r"<form|book now|booking|appointment|reserv|calendly|square\.site|fresha|vagaro|"
                        r"schedul|order online", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|copyright)\s*(?:(?:19|20)\d{2}\s*[-–]\s*)?((?:19|20)\d{2})", re.I)


@dataclass
class Result:
    url: str
    final_url: str = ""
    status: str = "ok"          # ok, down, error
    http: int | None = None
    seconds: float | None = None
    platform: str = ""
    copyright_year: int | None = None
    score: int = 0
    problems: list[str] = field(default_factory=list)

    def add(self, points: int, problem: str) -> None:
        self.score += points
        self.problems.append(problem)


def normalize(url: str) -> str:
    url = url.strip()
    return url if "://" in url else "http://" + url


def fetch(url: str, timeout: float) -> tuple[int, str, bytes, float]:
    """GET a URL following redirects. Returns (status, final_url, body, seconds)."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read(MAX_BYTES)
            return resp.status, resp.geturl(), body, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.geturl() or url, e.read(MAX_BYTES) if e.fp else b"", time.monotonic() - t0


def audit(url: str, timeout: float = 15.0, this_year: int | None = None) -> Result:
    this_year = this_year or dt.date.today().year
    url = normalize(url)
    r = Result(url=url)
    try:
        code, final, body, secs = fetch(url, timeout)
    except urllib.error.URLError as e:
        reason = e.reason
        r.status = "down"
        if isinstance(reason, ssl.SSLError):
            r.add(9, "broken SSL certificate: browsers show a security warning")
        elif isinstance(reason, socket.gaierror):
            r.add(10, "domain does not resolve: the website is gone")
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            r.add(9, f"does not load within {timeout:.0f} s")
        else:
            r.add(10, f"not responding ({reason})")
        return r
    except (TimeoutError, socket.timeout):
        r.status = "down"
        r.add(9, f"does not load within {timeout:.0f} s")
        return r
    except Exception as e:  # noqa: BLE001 - one bad site must not stop the batch
        r.status = "error"
        r.add(8, f"could not be opened ({type(e).__name__})")
        return r

    html = body.decode("utf-8", "replace")
    low = html.lower()
    r.http, r.final_url, r.seconds = code, final, round(secs, 1)

    if code >= 400:
        r.status = "error"
        r.add(9, f"returns HTTP {code}")
    placeholder = True
    if any(m in low for m in EXPIRED_MARKERS) or final.rstrip("/").endswith("/lander"):
        r.add(10, "expired or parked domain: the real website no longer exists")
    elif any(m in low for m in PARKED_MARKERS):
        r.add(8, "domain parked or for sale")
    elif any(m in low for m in CONSTRUCTION_MARKERS) and len(low) < 20000:
        r.add(6, "under construction / placeholder page")
    else:
        placeholder = False
    if len(SPAM_RE.findall(html)) >= 3:
        r.add(10, "domain shows spam (gambling/pharma): likely lost or hijacked")

    host_from = urllib.parse.urlparse(url).hostname or ""
    host_to = urllib.parse.urlparse(final).hostname or ""
    if host_to and host_from and _base(host_to) != _base(host_from):
        r.add(3, f"redirects to another domain ({host_to})")
    if not final.startswith("https://"):
        r.add(3, "no HTTPS: browsers label it 'Not secure'")
    if not re.search(r"<meta[^>]+name=[\"']?viewport", low):
        r.add(3, "not mobile-friendly (no viewport meta tag)")
    years = [int(y) for y in COPYRIGHT_RE.findall(html)]
    if years:
        r.copyright_year = max(years)
        age = this_year - r.copyright_year
        if age >= 5:
            r.add(3, f"copyright {r.copyright_year}: looks abandoned")
        elif age >= 3:
            r.add(2, f"copyright {r.copyright_year}: not updated recently")
    if "<frameset" in low or ".swf" in low:
        r.add(3, "uses frames or Flash")
    m = re.search(r"jquery[.-]?(1\.\d+)", low)
    if m:
        r.add(1, f"old jQuery {m.group(1)}")
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title_text = title.group(1).strip().lower() if title else ""
    if title_text in ("", "home", "index", "untitled", "welcome", "new page"):
        r.add(1, "no useful page title (hurts Google results)")
    if not re.search(r"<meta[^>]+name=[\"']?description", low):
        r.add(1, "no meta description (hurts Google results)")
    if "tel:" not in low:
        r.add(1, "phone number is not tap-to-call")
    if not BOOKING_RE.search(html):
        r.add(1, "no contact form or online booking")
    if secs > 5:
        r.add(2, f"slow ({secs:.1f} s)")
    if len(body) < 3000 and code < 400 and not placeholder:
        r.add(4, "almost empty page")

    gen = re.search(r"<meta[^>]+name=[\"']generator[\"'][^>]+content=[\"']([^\"']+)", html, re.I)
    if gen:
        r.platform = gen.group(1)[:40]
    else:
        r.platform = next((name for key, name in BUILDERS if key in low), "")
    return r


def _base(host: str) -> str:
    return ".".join(host.lower().removeprefix("www.").split(".")[-2:])


def read_urls(path: str, column: str | None) -> list[str]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        if path.lower().endswith(".csv"):
            rows = list(csv.DictReader(fh))
            if not rows:
                return []
            col = column or next((c for c in rows[0] if c.lower() in ("url", "website", "web", "site")), None)
            if col is None or col not in rows[0]:
                raise SystemExit(f"{path}: no URL column found; pass --column (have: {', '.join(rows[0])})")
            urls = [row[col] for row in rows]
        else:
            urls = [line for line in fh]
    seen, out = set(), []
    for u in (u.strip() for u in urls):
        if not u or u.startswith("#"):
            continue
        key = normalize(u).lower().rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def run(urls: list[str], workers: int, timeout: float) -> list[Result]:
    with cf.ThreadPoolExecutor(max(1, workers)) as ex:
        results = list(ex.map(lambda u: audit(u, timeout), urls))
    return sorted(results, key=lambda r: -r.score)


def write_csv(results: list[Result], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["score", "url", "final_url", "status", "http", "seconds", "platform", "copyright", "problems"])
        for r in results:
            w.writerow([r.score, r.url, r.final_url, r.status, r.http or "", r.seconds or "",
                        r.platform, r.copyright_year or "", "; ".join(r.problems)])


def write_markdown(results: list[Result], path: str) -> None:
    lines = ["# Website health report", "",
             f"{len(results)} sites checked on {dt.date.today():%Y-%m-%d}. Higher score = needs more work.", "",
             "| Score | Site | Main problems |", "|---:|---|---|"]
    for r in results:
        lines.append(f"| {r.score} | {r.url} | {'; '.join(r.problems[:4]) or 'no major problems'} |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("input", help="text file with one URL per line, or a CSV")
    p.add_argument("--column", help="CSV column with the URL (default: url/website/web/site)")
    p.add_argument("--csv", help="write the full report to this CSV")
    p.add_argument("--md", help="write a Markdown summary to this file")
    p.add_argument("--workers", type=int, default=8, help="parallel requests (default 8)")
    p.add_argument("--timeout", type=float, default=15.0, help="seconds per site (default 15)")
    p.add_argument("--min-score", type=int, default=0, help="only report sites with at least this score")
    args = p.parse_args(argv)

    urls = read_urls(args.input, args.column)
    if not urls:
        print("no URLs found", file=sys.stderr)
        return 1
    results = [r for r in run(urls, args.workers, args.timeout) if r.score >= args.min_score]
    for r in results:
        print(f"{r.score:>3}  {r.url[:45]:<45}  {'; '.join(r.problems[:3])}")
    if args.csv:
        write_csv(results, args.csv)
    if args.md:
        write_markdown(results, args.md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
