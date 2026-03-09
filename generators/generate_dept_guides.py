#!/usr/bin/env python3
"""Generate "How to Use AI in [Department]" guides for all 12 departments.

Weekly mode (default): finds the guide with the oldest added_date and
regenerates it with a fresh angle.

Seed mode (--all): generates guides for ALL departments from scratch.

Usage:
    python generate_dept_guides.py                        # weekly — refresh oldest guide
    python generate_dept_guides.py --all                  # seed all 12 departments
    python generate_dept_guides.py --department=marketing # one department only
    python generate_dept_guides.py --dry-run              # preview without writing
"""

import json
import re
import sys
import time
import argparse
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))
from llm_providers import generate

AGENTS_DIR = BASE_DIR.parent / "agents"
AGENTS_DATA = AGENTS_DIR / "agents_data.json"
GUIDES_FILE = AGENTS_DIR / "guides_data.json"

TODAY = date.today().isoformat()

GENERATION_PROMPT = """You are writing a practical "How to Use AI in {dept_name}" guide for professionals.

This guide will live in an AI Agent Library. Audience: working professionals who want actionable AI adoption advice — not theory, not fluff.

DEPARTMENT: {dept_name}
AVAILABLE AGENTS FOR THIS DEPARTMENT:
{agent_list}

Generate a guide with exactly this structure:
- id: "{dept_slug}"
- title: "How to Use AI in {dept_name}"
- intro: 2-3 sentences on how AI is transforming this specific department. Be concrete, not generic.
- steps: exactly 5 practical steps. Each step has:
  - title: short action-oriented title (3-6 words)
  - body: 2-3 sentences. Specific, actionable. Reference real workflows or tools where helpful.
- pro_tips: exactly 3 pro tips. Each is 1-2 sentences. Insider advice a practitioner would give.
- recommended_agents: exactly 3 agent IDs from this list (pick the most relevant): {agent_ids}

Rules:
- No fluff, no "AI can help you..." vagueness
- Each step should be something you can actually do this week
- Pro tips should feel like hard-won advice, not textbook content
- recommended_agents must be exact IDs from the provided list

Return ONLY a JSON object:
{{
  "id": "{dept_slug}",
  "dept_slug": "{dept_slug}",
  "title": "How to Use AI in {dept_name}",
  "intro": "<2-3 sentences>",
  "steps": [
    {{"title": "<short title>", "body": "<2-3 sentences>"}},
    {{"title": "<short title>", "body": "<2-3 sentences>"}},
    {{"title": "<short title>", "body": "<2-3 sentences>"}},
    {{"title": "<short title>", "body": "<2-3 sentences>"}},
    {{"title": "<short title>", "body": "<2-3 sentences>"}}
  ],
  "pro_tips": ["<tip 1>", "<tip 2>", "<tip 3>"],
  "recommended_agents": ["<agent-id-1>", "<agent-id-2>", "<agent-id-3>"]
}}

Return ONLY the JSON object, no other text."""


def load_agents_data():
    with open(AGENTS_DATA) as f:
        return json.load(f)


def load_guides_data():
    if GUIDES_FILE.exists():
        with open(GUIDES_FILE) as f:
            return json.load(f)
    return {"meta": {"updated": TODAY}, "guides": []}


def find_oldest_guide(guides):
    if not guides:
        return None
    oldest = min(guides, key=lambda g: g.get("added_date", "1970-01-01"))
    return oldest["dept_slug"]


def get_dept_agents(dept):
    return [(a["id"], a["title"], a.get("tags", [])) for a in dept["agents"]]


def generate_for_department(dept_slug, dept):
    agents = get_dept_agents(dept)
    agent_ids = [a[0] for a in agents]

    agent_list_lines = "\n".join(
        f"  - {a[0]} ({a[1]}) — tags: {', '.join(a[2])}" for a in agents
    )

    prompt = GENERATION_PROMPT.format(
        dept_name=dept["name"],
        dept_slug=dept_slug,
        agent_list=agent_list_lines,
        agent_ids=", ".join(agent_ids),
    )

    try:
        response = generate(prompt, chain="fast")

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            print(f"    No JSON found in response for {dept_slug}")
            return None

        data = json.loads(json_match.group())

        required = ["id", "dept_slug", "title", "intro", "steps", "pro_tips", "recommended_agents"]
        for field in required:
            if field not in data:
                print(f"    Missing field '{field}' for {dept_slug}")
                return None

        if len(data.get("steps", [])) != 5:
            print(f"    Expected 5 steps, got {len(data.get('steps', []))} for {dept_slug}")
            return None

        if len(data.get("pro_tips", [])) != 3:
            print(f"    Expected 3 pro_tips, got {len(data.get('pro_tips', []))} for {dept_slug}")
            return None

        valid_ids = set(a[0] for a in agents)
        data["recommended_agents"] = [
            aid for aid in data["recommended_agents"] if aid in valid_ids
        ][:3]

        data["id"] = dept_slug
        data["dept_slug"] = dept_slug
        data["added_date"] = TODAY

        return data

    except json.JSONDecodeError as e:
        print(f"    JSON parse error for {dept_slug}: {e}")
        return None
    except Exception as e:
        print(f"    Generation failed for {dept_slug}: {e}")
        return None


def upsert_guide(guides_list, new_guide):
    for i, g in enumerate(guides_list):
        if g["dept_slug"] == new_guide["dept_slug"]:
            guides_list[i] = new_guide
            return guides_list, "updated"
    guides_list.append(new_guide)
    return guides_list, "added"


def run(target_dept=None, seed_all=False, dry_run=False):
    agents_data = load_agents_data()
    guides_data = load_guides_data()
    departments = agents_data["departments"]

    generated = 0
    failed = 0

    if seed_all:
        targets = list(departments.keys())
        print(f"Seed mode: generating guides for all {len(targets)} departments")
    elif target_dept:
        if target_dept not in departments:
            print(f"Unknown department: {target_dept}")
            print(f"Valid options: {', '.join(departments.keys())}")
            return 0
        targets = [target_dept]
        print(f"Single department mode: {target_dept}")
    else:
        oldest_slug = find_oldest_guide(guides_data["guides"])
        if oldest_slug is None:
            oldest_slug = list(departments.keys())[0]
            print(f"No existing guides found. Starting with: {oldest_slug}")
        else:
            oldest_entry = next(
                (g for g in guides_data["guides"] if g["dept_slug"] == oldest_slug), None
            )
            oldest_date = oldest_entry.get("added_date", "unknown") if oldest_entry else "unknown"
            print(f"Weekly mode: refreshing oldest guide — {oldest_slug} (last updated: {oldest_date})")
        targets = [oldest_slug]

    for dept_slug in targets:
        dept = departments[dept_slug]
        print(f"  [{dept_slug}] Generating guide for '{dept['name']}'...")

        new_guide = generate_for_department(dept_slug, dept)

        if not new_guide:
            print(f"    FAILED: {dept_slug}")
            failed += 1
            continue

        if dry_run:
            print(f"    [DRY RUN] Would write: {new_guide['title']}")
            print(f"    Intro: {new_guide['intro'][:80]}...")
            print(f"    Steps: {[s['title'] for s in new_guide['steps']]}")
            generated += 1
            continue

        guides_data["guides"], action = upsert_guide(guides_data["guides"], new_guide)
        print(f"    {action.capitalize()}: {new_guide['title']}")
        generated += 1

        if len(targets) > 1:
            time.sleep(2)

    if not dry_run and generated > 0:
        guides_data["meta"]["updated"] = TODAY
        with open(GUIDES_FILE, "w") as f:
            json.dump(guides_data, f, indent=2)
        print(f"\nSaved {GUIDES_FILE}")

    print(f"\nGenerated: {generated}, Failed: {failed}")
    return generated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Generate "How to Use AI in [Department]" guides'
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to disk")
    parser.add_argument("--department", type=str, metavar="SLUG", help="Generate for one department only")
    parser.add_argument("--all", dest="seed_all", action="store_true", help="Generate guides for ALL departments")
    args = parser.parse_args()

    run(target_dept=args.department, seed_all=args.seed_all, dry_run=args.dry_run)
