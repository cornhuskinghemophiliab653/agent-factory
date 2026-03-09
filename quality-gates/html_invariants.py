#!/usr/bin/env python3
"""
html_invariants.py — Universal HTML invariant checker for static sites.

Enforces "things that must always be true" across your site repos.
Site-config-driven — different sites have different rules.

Exit code 0 = all invariants hold, 1 = violations found.

Usage:
  python html_invariants.py                    # check all configured sites
  python html_invariants.py --site mysite      # check one site
  python html_invariants.py --notify           # post Discord/Slack summary on failure
  python html_invariants.py --json             # output JSON report

Configuration:
  Edit the SITES dict below to add your own sites and their check rules.
  Each check can be 'error' (blocks pipeline) or 'warning' (advisory).
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# ── Site configurations ──
# Add your sites here. Each site defines which invariants are enforced.

SITES = {
    'example-site': {
        'dir_env': 'EXAMPLE_SITE_DIR',       # env var pointing to site dir
        'dir_default': 'example-site',         # fallback directory name
        'domain': 'example.com',
        'checks': {
            'title': 'error',           # <title> tag required
            'viewport': 'error',        # viewport meta required
            'description': 'error',     # meta description required
            'canonical': 'error',       # canonical link required
            'og_title': 'warning',      # Open Graph title
            'og_description': 'warning',# Open Graph description
            'og_url': 'warning',        # Open Graph URL
            'og_image': 'warning',      # Open Graph image
            'jsonld': 'warning',        # JSON-LD structured data
            'cf_beacon': 'warning',     # Cloudflare Web Analytics beacon
            'broken_links': 'error',    # internal link targets exist
            'broken_images': 'error',   # image src files exist
            'placeholder': 'error',     # no PLACEHOLDER text
        },
        'skip': ['404.html'],  # skip meta checks for these files
    },
}


def resolve_site_dir(site_name, cfg):
    """Find the site directory — check env var, then common locations."""
    if cfg['dir_env'] in os.environ:
        return os.environ[cfg['dir_env']]

    project_root = os.environ.get('PROJECT_ROOT', '')
    candidates = [
        os.path.join(project_root, cfg['dir_default']),
        os.path.join(Path(__file__).parent.parent, cfg['dir_default']),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return str(Path(c).resolve())
    return None


def check_html(html, rel_path, site_dir, cfg):
    """Check a single HTML file against configured invariants."""
    errs, warns = [], []
    checks = cfg['checks']
    skip = cfg.get('skip', [])
    fpath = f"{os.path.basename(site_dir)}/{rel_path}"

    skip_meta = any(rel_path.endswith(s) for s in skip)
    if 'http-equiv="refresh"' in html:
        skip_meta = True

    def report(check_name, msg):
        level = checks.get(check_name, 'warning')
        if level == 'error':
            errs.append(msg)
        elif level == 'warning':
            warns.append(msg)

    html_no_script = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)

    # Broken internal links
    if 'broken_links' in checks:
        for m in re.finditer(r'<a\s[^>]*href="(/[^"]*)"', html_no_script):
            href = m.group(1)
            if href.startswith(('/cdn-cgi/', '/api/')) or href == '/':
                continue
            target = href.split('?')[0].split('#')[0].rstrip('/')
            if not target:
                continue
            base = target.lstrip('/')
            if '.' not in base.split('/')[-1]:
                candidates = [Path(site_dir) / (base + '.html'), Path(site_dir) / base / 'index.html']
            else:
                candidates = [Path(site_dir) / base]
            if not any(c.exists() for c in candidates):
                report('broken_links', f"BROKEN LINK: {fpath} -> {href}")

    if 'broken_images' in checks:
        for m in re.finditer(r'<img[^>]+src="(/[^"]*)"', html):
            src = m.group(1)
            if not (Path(site_dir) / src.lstrip('/')).exists():
                report('broken_images', f"BROKEN IMAGE: {fpath} -> {src}")

    if 'placeholder' in checks and 'PLACEHOLDER' in html:
        report('placeholder', f"PLACEHOLDER TEXT: {fpath}")

    if skip_meta:
        return errs, warns

    if 'title' in checks and not re.search(r'<title[^>]*>.+</title>', html, re.DOTALL):
        report('title', f"MISSING TITLE: {fpath}")
    if 'viewport' in checks and not re.search(r'name="viewport"', html):
        report('viewport', f"MISSING VIEWPORT: {fpath}")
    if 'description' in checks and not re.search(r'name="description"', html):
        report('description', f"MISSING META DESC: {fpath}")
    if 'canonical' in checks and not re.search(r'rel="canonical"', html):
        report('canonical', f"MISSING CANONICAL: {fpath}")
    if 'og_title' in checks and not re.search(r'og:title', html):
        report('og_title', f"MISSING OG:TITLE: {fpath}")
    if 'og_description' in checks and not re.search(r'og:description', html):
        report('og_description', f"MISSING OG:DESC: {fpath}")
    if 'og_url' in checks and not re.search(r'og:url', html):
        report('og_url', f"MISSING OG:URL: {fpath}")
    if 'og_image' in checks and not re.search(r'og:image', html):
        report('og_image', f"MISSING OG:IMAGE: {fpath}")
    if 'jsonld' in checks and not re.search(r'application/ld\+json', html):
        report('jsonld', f"MISSING JSON-LD: {fpath}")
    if 'cf_beacon' in checks and 'beacon.min.js' not in html:
        report('cf_beacon', f"MISSING CF BEACON: {fpath}")

    return errs, warns


def check_site(site_name, cfg):
    """Check all HTML files in a site."""
    site_dir = resolve_site_dir(site_name, cfg)
    if not site_dir:
        return [], [f"SITE NOT FOUND: {site_name}"], 0

    all_errors, all_warnings = [], []
    file_count = 0

    for root, dirs, files in os.walk(site_dir):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '.cloudflare')]
        for f in files:
            if not f.endswith('.html'):
                continue
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, site_dir)
            try:
                html = Path(fpath).read_text(errors='replace')
            except Exception:
                all_errors.append(f"UNREADABLE: {site_name}/{rel}")
                continue
            errs, warns = check_html(html, rel, site_dir, cfg)
            all_errors.extend(errs)
            all_warnings.extend(warns)
            file_count += 1

    return all_errors, all_warnings, file_count


def main():
    parser = argparse.ArgumentParser(description='HTML invariant checker')
    parser.add_argument('--site', help='Check a single site')
    parser.add_argument('--notify', action='store_true', help='Post to Discord on failure')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    args = parser.parse_args()

    sites_to_check = {args.site: SITES[args.site]} if args.site else SITES
    if args.site and args.site not in SITES:
        print(f"Unknown site: {args.site}. Available: {', '.join(SITES.keys())}")
        sys.exit(1)

    total_errors, total_warnings, total_files = 0, 0, 0
    report = {}

    for site_name, cfg in sites_to_check.items():
        errs, warns, count = check_site(site_name, cfg)
        report[site_name] = {'errors': errs, 'warnings': warns, 'files': count}
        total_errors += len(errs)
        total_warnings += len(warns)
        total_files += count
        status = 'PASS' if not errs else 'FAIL'
        print(f"  {status}  {site_name}: {count} files, {len(errs)} errors, {len(warns)} warnings")

    print(f"\n{'='*60}")
    print(f"  HTML INVARIANTS — {total_files} files across {len(sites_to_check)} sites")
    print(f"  {total_errors} errors, {total_warnings} warnings")
    print(f"{'='*60}")

    if total_errors:
        print(f"\nERRORS ({total_errors}):")
        for data in report.values():
            for e in sorted(data['errors']):
                print(f"  {e}")

    if args.json:
        os.makedirs('output', exist_ok=True)
        with open('output/html-invariants.json', 'w') as f:
            json.dump({'timestamp': datetime.now(timezone.utc).isoformat(),
                       'total_files': total_files, 'total_errors': total_errors,
                       'total_warnings': total_warnings, 'sites': report}, f, indent=2)

    if args.notify and total_errors:
        webhook = os.environ.get('DISCORD_WEBHOOK_ALERTS', '')
        if webhook:
            try:
                import requests
                requests.post(webhook, json={'content': f"HTML Invariants: {total_errors} errors"[:2000]}, timeout=10)
            except Exception:
                pass

    sys.exit(1 if total_errors else 0)


if __name__ == '__main__':
    sys.exit(main() or 0)
