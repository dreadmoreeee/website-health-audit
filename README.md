# website-health-audit

Check a list of small-business websites in one go and rank them from worst to best.

For every URL it looks at what a customer (and Google) runs into:

- **Gone:** the domain no longer resolves, the server does not answer, the SSL certificate is broken.
- **Expired or parked:** registrar "lander" pages (including the JavaScript redirect GoDaddy uses), "Website expired" pages from site builders, domains for sale, "coming soon" placeholders.
- **Hijacked:** the old domain now shows gambling or pharma spam.
- **Outdated:** no HTTPS, not mobile-friendly, copyright year 3+ years old, frames/Flash, old jQuery.
- **Losing customers:** phone number not tap-to-call, no contact form or online booking, slow first load, no page title or meta description.

Each problem adds points, so the report is sorted by how badly the site needs work. I use it to find local businesses whose website is broken before offering to fix it.

- **Standard library only.** No `requests`, no browser. Python 3.10+.
- **Reads a text file (one URL per line) or a CSV** with a `url`/`website` column, de-duplicates and skips blanks.
- **Parallel** (8 workers by default) with a per-site timeout, and one bad site never stops the batch.

## Measured result

```
$ python site_audit.py sample_urls.txt --md sample_report.md --workers 4
 10  http://example.com                             no HTTPS: browsers label it 'Not secure'; no meta description (hurts Google results); phone number is not tap-to-call
 10  http://this-business-closed-years-ago.invalid  domain does not resolve: the website is gone
  2  https://www.python.org                         old jQuery 1.8; phone number is not tap-to-call
  1  https://demarkstudio.ca                        phone number is not tap-to-call

$ python -m pytest -q
.........
9 passed in 0.78s
```

The tests start a local HTTP server that serves a healthy page, an outdated one, a GoDaddy-style JavaScript parking redirect, a spam takeover and a 404, so they run offline in under a second.

On a real list of 187 business websites in one Canadian city it found 7 expired/parked domains, 2 hijacked by gambling spam and 28 that were down (domain gone or server not answering).

## Usage

```bash
python site_audit.py urls.txt                                  # table in the terminal
python site_audit.py leads.csv --column website --csv report.csv --md report.md
python site_audit.py urls.txt --min-score 6 --timeout 10       # only sites that clearly need work
```

`report.csv` columns: `score, url, final_url, status, http, seconds, platform, copyright, problems`.

Scores are a triage aid, not a verdict: some healthy sites block automated requests (HTTP 403), so open the top results in a browser before contacting anyone.

## Author

Marvin Palencia, founder of [DeMark Studio](https://demarkstudio.ca), Miramichi, New Brunswick, Canada. I build websites, Stripe payment integrations and Python automations for small businesses. Portfolio: [marvin.demarkstudio.ca](https://marvin.demarkstudio.ca)

MIT License.
