#!/usr/bin/env python3
"""
check_imports.py — Verify that top-level imports in Python scripts resolve.

Uses importlib.util.find_spec() instead of __import__() to avoid executing
module-level code (which would fail without API keys in CI).

Skips local project modules (any .py file in the repo).

Exit code 0 = all imports resolve, 1 = missing imports found.

Usage:
  python check_imports.py                    # check default scripts list
  python check_imports.py script1.py script2.py  # check specific scripts

Configuration:
  Edit the SCRIPTS list below to add your own pipeline scripts.
"""
import ast
import importlib.util
import os
import sys

# ── Scripts to check (edit this list) ──
SCRIPTS = [
    # Add your critical pipeline scripts here
    # 'pipeline.py',
    # 'app.py',
]


def collect_local_modules():
    """Collect all .py filenames in the repo as local module names."""
    local = set()
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d != '.git']
        for fn in files:
            if fn.endswith('.py'):
                local.add(fn[:-3])
    return local


def check_file(filepath, local_mods):
    """Check that all imports in a file can be found. Returns list of missing imports."""
    missing = []
    try:
        with open(filepath) as fh:
            tree = ast.parse(fh.read())
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split('.')[0]
                if top in local_mods:
                    continue
                if importlib.util.find_spec(top) is None:
                    missing.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split('.')[0]
            if top in local_mods:
                continue
            if importlib.util.find_spec(top) is None:
                missing.append(node.module)

    return list(dict.fromkeys(missing))


def main():
    local_mods = collect_local_modules()

    # Allow passing scripts as CLI args, otherwise use SCRIPTS list
    scripts = sys.argv[1:] if len(sys.argv) > 1 else SCRIPTS

    if not scripts:
        print("No scripts to check. Edit SCRIPTS list or pass files as arguments.")
        return 0

    fail = False
    for script in scripts:
        if not os.path.isfile(script):
            continue
        missing = check_file(script, local_mods)
        if missing:
            for m in missing:
                print(f"Missing: {m} (in {script})")
            fail = True
        else:
            print(f"  OK  {script}")

    if fail:
        print("\nImport check FAILED")
        return 1

    print("\nAll critical imports resolve OK")
    return 0


if __name__ == '__main__':
    sys.exit(main())
