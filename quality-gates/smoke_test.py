#!/usr/bin/env python3
"""
smoke_test.py — Post-deploy smoke test for your sites.

HTTP pings each site's index + sample pages to verify they're live
and returning expected content. Catches publish failures, DNS issues,
and broken deploys.

Exit code 0 = all sites healthy, 1 = failures found.

Usage:
  python smoke_test.py                        # check all sites
  python smoke_test.py --site example.com     # check one site
  python smoke_test.py --json                 # output JSON report

Configuration:
  Edit the SITES dict below with your own URLs and expected content strings.
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── Sites and their smoke test URLs ──
# Each entry: (url, required_string_in_html)
SITES = {
    'example.com': {
        'urls': [
            ('https://example.com/', '<title>'),
            ('https://example.com/about', '<title>'),
        ],
    },
}

TIMEOUT = 15
USER_AGENT = 'SmokeTest/1.0'


def check_url(url, required_string):
    try:
        req = Request(url, headers={'User-Agent': USER_AGENT})
        resp = urlopen(req, timeout=TIMEOUT)
        code = resp.getcode()
        body = resp.read().decode('utf-8', errors='replace')[:10000]

        if code != 200:
            return (url, 'error', f"HTTP {code}")
        if required_string and required_string not in body:
            return (url, 'error', f"missing expected content: {required_string}")
        return (url, 'ok', f"HTTP {code}, {len(body)} bytes")

    except HTTPError as e:
        return (url, 'error', f"HTTP {e.code}")
    except URLError as e:
        return (url, 'error', f"connection failed: {e.reason}")
    except Exception as e:
        return (url, 'error', str(e))


def smoke_test(sites_to_check):
    results = {}
    tasks = []

    with ThreadPoolExecutor(max_workers=10) as pool:
        for site_name, cfg in sites_to_check.items():
            results[site_name] = []
            for url, required in cfg['urls']:
                future = pool.submit(check_url, url, required)
                tasks.append((site_name, url, future))

        for site_name, url, future in tasks:
            url_result, status, detail = future.result()
            results[site_name].append({'url': url_result, 'status': status, 'detail': detail})

    return results


def main():
    parser = argparse.ArgumentParser(description='Post-deploy smoke test')
    parser.add_argument('--site', help='Check a single site (domain name)')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    args = parser.parse_args()

    sites_to_check = {args.site: SITES[args.site]} if args.site else SITES
    results = smoke_test(sites_to_check)

    total_ok, total_fail = 0, 0
    for site_name, checks in results.items():
        fails = [c for c in checks if c['status'] != 'ok']
        oks = [c for c in checks if c['status'] == 'ok']
        total_ok += len(oks)
        total_fail += len(fails)
        status = 'PASS' if not fails else 'FAIL'
        print(f"  {status}  {site_name}: {len(oks)}/{len(checks)} OK")
        for f in fails:
            print(f"         {f['url']} — {f['detail']}")

    print(f"\n{'='*60}")
    print(f"  SMOKE TEST — {total_ok + total_fail} URLs across {len(sites_to_check)} sites")
    print(f"  {total_ok} OK, {total_fail} failed")
    print(f"{'='*60}")

    if args.json:
        os.makedirs('output', exist_ok=True)
        with open('output/smoke-test.json', 'w') as f:
            json.dump({'timestamp': datetime.now(timezone.utc).isoformat(),
                       'total_ok': total_ok, 'total_fail': total_fail, 'sites': results}, f, indent=2)

    return 1 if total_fail else 0


if __name__ == '__main__':
    sys.exit(main())
