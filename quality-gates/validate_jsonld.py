#!/usr/bin/env python3
"""
validate_jsonld.py — Structured data (JSON-LD) validator for static sites.

Goes beyond "is JSON-LD present" to validate:
  - Valid JSON syntax
  - Has required @context and @type
  - Required fields per schema type (WebSite, Person, Organization, etc.)
  - No empty/placeholder values

Exit code 0 = all valid, 1 = errors found.

Usage:
  python validate_jsonld.py                    # check all sites
  python validate_jsonld.py --site mysite      # check one site
  python validate_jsonld.py --json             # output JSON report

Configuration:
  Edit the SITES dict below to add your own sites.
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# ── Site configs (edit this) ──
SITES = {
    'example-site': {'dir_env': 'EXAMPLE_SITE_DIR', 'dir_default': 'example-site'},
}

# ── Required fields per @type ──
REQUIRED_FIELDS = {
    'WebSite': ['name', 'url'],
    'Person': ['name'],
    'Organization': ['name', 'url'],
    'Article': ['headline', 'author'],
    'NewsArticle': ['headline', 'author'],
    'BlogPosting': ['headline', 'author'],
    'CreativeWork': ['name'],
    'Product': ['name'],
    'AboutPage': ['name'],
    'WebPage': ['name'],
    'FAQPage': ['mainEntity'],
    'BreadcrumbList': ['itemListElement'],
    'SearchAction': [],
}

SKIP_FILES = {'404.html'}


def resolve_site_dir(site_name, cfg):
    if cfg['dir_env'] in os.environ:
        return os.environ[cfg['dir_env']]
    for c in [os.path.join(os.environ.get('PROJECT_ROOT', ''), cfg['dir_default']),
              os.path.join(Path(__file__).parent.parent, cfg['dir_default'])]:
        if os.path.isdir(c):
            return str(Path(c).resolve())
    return None


def validate_jsonld_block(raw_json, fpath, block_num):
    errs, warns = [], []
    prefix = f"{fpath} [block {block_num}]"

    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        errs.append(f"INVALID JSON: {prefix} — {e}")
        return errs, warns

    items = []
    if isinstance(data, list):
        items = data
    elif '@graph' in data:
        items = data['@graph'] if isinstance(data['@graph'], list) else [data['@graph']]
    else:
        items = [data]

    for item in items:
        if not isinstance(item, dict):
            continue

        if block_num == 1 and '@context' not in data and '@context' not in item:
            warns.append(f"MISSING @context: {prefix}")

        schema_type = item.get('@type', '')
        if not schema_type:
            warns.append(f"MISSING @type: {prefix}")
            continue

        if isinstance(schema_type, list):
            schema_type = schema_type[0]

        required = REQUIRED_FIELDS.get(schema_type, [])
        for field in required:
            val = item.get(field)
            if val is None or val == '' or val == []:
                errs.append(f"MISSING {schema_type}.{field}: {prefix}")
            elif isinstance(val, str) and 'PLACEHOLDER' in val.upper():
                errs.append(f"PLACEHOLDER in {schema_type}.{field}: {prefix}")

    return errs, warns


def validate_file(html, rel_path, site_name):
    all_errs, all_warns = [], []
    fpath = f"{site_name}/{rel_path}"

    blocks = re.findall(
        r'<script\s+type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )

    if not blocks:
        return all_errs, all_warns

    for i, raw in enumerate(blocks, 1):
        raw = raw.strip()
        if not raw:
            all_errs.append(f"EMPTY JSON-LD: {fpath} [block {i}]")
            continue
        errs, warns = validate_jsonld_block(raw, fpath, i)
        all_errs.extend(errs)
        all_warns.extend(warns)

    return all_errs, all_warns


def check_site(site_name, cfg):
    site_dir = resolve_site_dir(site_name, cfg)
    if not site_dir:
        return [], [f"SITE NOT FOUND: {site_name}"], 0

    all_errors, all_warnings = [], []
    file_count = 0

    for root, dirs, files in os.walk(site_dir):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', '.cloudflare')]
        for f in files:
            if not f.endswith('.html') or f in SKIP_FILES:
                continue
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, site_dir)
            try:
                html = Path(fpath).read_text(errors='replace')
            except Exception:
                continue
            errs, warns = validate_file(html, rel, site_name)
            all_errors.extend(errs)
            all_warnings.extend(warns)
            if 'application/ld+json' in html:
                file_count += 1

    return all_errors, all_warnings, file_count


def main():
    parser = argparse.ArgumentParser(description='JSON-LD structured data validator')
    parser.add_argument('--site', help='Check a single site')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    args = parser.parse_args()

    sites_to_check = {args.site: SITES[args.site]} if args.site else SITES
    total_errors, total_warnings, total_files = 0, 0, 0
    report = {}

    for site_name, cfg in sites_to_check.items():
        errs, warns, count = check_site(site_name, cfg)
        report[site_name] = {'errors': errs, 'warnings': warns, 'files_with_jsonld': count}
        total_errors += len(errs)
        total_warnings += len(warns)
        total_files += count
        status = 'PASS' if not errs else 'FAIL'
        print(f"  {status}  {site_name}: {count} files, {len(errs)} errors, {len(warns)} warnings")

    print(f"\n{'='*60}")
    print(f"  JSON-LD VALIDATION — {total_files} files across {len(sites_to_check)} sites")
    print(f"  {total_errors} errors, {total_warnings} warnings")
    print(f"{'='*60}")

    if total_errors:
        print(f"\nERRORS ({total_errors}):")
        for data in report.values():
            for e in sorted(data['errors']):
                print(f"  {e}")

    if args.json:
        os.makedirs('output', exist_ok=True)
        with open('output/jsonld-validation.json', 'w') as f:
            json.dump({'timestamp': datetime.now(timezone.utc).isoformat(),
                       'total_files': total_files, 'total_errors': total_errors,
                       'total_warnings': total_warnings, 'sites': report}, f, indent=2)

    return 1 if total_errors else 0


if __name__ == '__main__':
    sys.exit(main())
