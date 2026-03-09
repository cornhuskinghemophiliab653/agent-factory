#!/usr/bin/env python3
"""
banned_patterns.py — Grep-based scanner for patterns that should never exist.

Scans repos for dead code, hardcoded secrets, debug leftovers,
and other patterns that indicate regressions.

Exit code 0 = clean, 1 = violations found.

Usage:
  python banned_patterns.py                  # check all repos
  python banned_patterns.py --repo myapp     # check one repo
  python banned_patterns.py --json           # output JSON report

Configuration:
  Edit REPOS to add your repositories and BANNED to add your patterns.
"""
import os
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# ── Repos to scan (edit this) ──
REPOS = {
    'myapp': {'dir_env': 'MYAPP_DIR', 'dir_default': 'myapp'},
}

# ── Banned patterns ──
# (regex, description, severity, file_extensions_or_None)
BANNED = [
    # Hardcoded secrets
    (r'sk-[a-zA-Z0-9]{20,}', 'possible hardcoded API key (sk-...)', 'error',
     ['.py', '.js', '.html', '.yml', '.yaml', '.sh']),
    (r'ghp_[a-zA-Z0-9]{36}', 'hardcoded GitHub PAT', 'error', None),
    (r'xoxb-[0-9]{10,}', 'hardcoded Slack token', 'error', None),

    # Debug leftovers
    (r'PLACEHOLDER', 'placeholder text in output', 'error', ['.html']),
    (r'breakpoint\(\)', 'Python breakpoint() left in code', 'error', ['.py']),
    (r'debugger;', 'JS debugger statement left in code', 'error', ['.js', '.html']),
    (r'console\.log\(', 'console.log left in production HTML', 'warning', ['.html']),
    (r'TODO.?FIXME', 'TODO+FIXME combo (urgent fix needed)', 'warning', ['.py', '.js']),
]

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'output', '.venv'}
SKIP_FILES = {'banned_patterns.py'}
SKIP_SUFFIXES = ('.pyc', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2',
                 '.ttf', '.eot', '.svg', '.mp4', '.mp3', '.pdf', '.zip', '.gz',
                 '.lock', '.map')


def resolve_repo_dir(repo_name, cfg):
    if cfg['dir_env'] in os.environ:
        return os.environ[cfg['dir_env']]
    project_root = os.environ.get('PROJECT_ROOT', '')
    for c in [os.path.join(project_root, cfg['dir_default']),
              os.path.join(Path(__file__).parent.parent, cfg['dir_default'])]:
        if os.path.isdir(c):
            return str(Path(c).resolve())
    return None


def scan_file(fpath, rel_path):
    errs, warns = [], []
    try:
        content = Path(fpath).read_text(errors='replace')
    except Exception:
        return errs, warns

    for pattern, desc, severity, file_filter in BANNED:
        if file_filter and not any(rel_path.endswith(ext) for ext in file_filter):
            continue
        for i, line in enumerate(content.splitlines(), 1):
            if re.search(pattern, line):
                stripped = line.strip()
                if stripped.startswith('#') or stripped.startswith('//'):
                    if 'removed' in stripped.lower() or 'no longer' in stripped.lower():
                        continue
                msg = f"{rel_path}:{i}: {desc}"
                (errs if severity == 'error' else warns).append(msg)
                break
    return errs, warns


def scan_repo(repo_name, cfg):
    repo_dir = resolve_repo_dir(repo_name, cfg)
    if not repo_dir:
        return [], [f"REPO NOT FOUND: {repo_name}"], 0

    all_errors, all_warnings = [], []
    file_count = 0

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f in SKIP_FILES or f.endswith(SKIP_SUFFIXES):
                continue
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, repo_dir)
            errs, warns = scan_file(fpath, rel)
            all_errors.extend([f"{repo_name}/{m}" for m in errs])
            all_warnings.extend([f"{repo_name}/{m}" for m in warns])
            file_count += 1

    return all_errors, all_warnings, file_count


def main():
    parser = argparse.ArgumentParser(description='Banned pattern scanner')
    parser.add_argument('--repo', help='Scan a single repo')
    parser.add_argument('--json', action='store_true', help='Output JSON report')
    args = parser.parse_args()

    repos_to_scan = {args.repo: REPOS[args.repo]} if args.repo else REPOS
    total_errors, total_warnings, total_files = 0, 0, 0
    report = {}

    for repo_name, cfg in repos_to_scan.items():
        errs, warns, count = scan_repo(repo_name, cfg)
        report[repo_name] = {'errors': errs, 'warnings': warns, 'files': count}
        total_errors += len(errs)
        total_warnings += len(warns)
        total_files += count
        status = 'PASS' if not errs else 'FAIL'
        print(f"  {status}  {repo_name}: {count} files, {len(errs)} errors, {len(warns)} warnings")

    print(f"\n{'='*60}")
    print(f"  BANNED PATTERNS — {total_files} files across {len(repos_to_scan)} repos")
    print(f"  {total_errors} errors, {total_warnings} warnings")
    print(f"{'='*60}")

    if total_errors:
        print(f"\nERRORS ({total_errors}):")
        for data in report.values():
            for e in sorted(data['errors']):
                print(f"  {e}")

    if not total_errors and not total_warnings:
        print("\nAll clean. No banned patterns found.")

    if args.json:
        os.makedirs('output', exist_ok=True)
        with open('output/banned-patterns.json', 'w') as f:
            json.dump({'timestamp': datetime.now(timezone.utc).isoformat(),
                       'total_files': total_files, 'total_errors': total_errors,
                       'total_warnings': total_warnings, 'repos': report}, f, indent=2)

    return 1 if total_errors else 0


if __name__ == '__main__':
    sys.exit(main())
