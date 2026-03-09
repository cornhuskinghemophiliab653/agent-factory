#!/usr/bin/env python3
"""Generate weekly bonus prompt recipes for the AI Agent Library.

Creates one new prompt per department per week. Rolling window of
MAX_PER_DEPT prompts per department — oldest rotates out when full.

Usage:
    python generate_bonus_prompts.py               # generate all departments
    python generate_bonus_prompts.py --dry-run      # preview without writing
    python generate_bonus_prompts.py --department=sales  # one department only
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
BONUS_FILE = AGENTS_DIR / "bonus_prompts.json"

MAX_PER_DEPT = 5
TODAY = date.today().isoformat()

GENERATION_PROMPT = """You are creating a practical AI prompt recipe for the "{dept_name}" department.

This prompt will be part of an AI Agent Library used by professionals. It should be a ready-to-use system prompt that someone can copy into Claude, GPT, or Gemini.

EXISTING AGENTS in this department (do NOT duplicate these):
{existing_titles}

PREVIOUSLY GENERATED bonus prompts (do NOT duplicate these either):
{bonus_titles}

Generate a NEW, practical AI agent prompt recipe that fills a gap in this department's coverage. Pick a specific, useful role that professionals actually need.

Return ONLY a JSON object with these fields:
{{
  "id": "<kebab-case-slug>",
  "title": "<Agent Title — 2-4 words>",
  "one_liner": "<One sentence describing what this agent does>",
  "prompt": "<The full system prompt — 150-300 words, professional, actionable. Include: expertise areas, how the agent works, deliverables, and 3-5 rules>",
  "deliverables": ["deliverable1", "deliverable2", "deliverable3"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}

Make the prompt practical and specific — not generic. A professional should be able to copy-paste it and get immediate value.
Return ONLY the JSON object, no other text."""


def load_agents_data():
    with open(AGENTS_DATA) as f:
        return json.load(f)


def load_bonus_data():
    if BONUS_FILE.exists():
        with open(BONUS_FILE) as f:
            return json.load(f)
    return {"meta": {"generated": TODAY, "max_per_dept": MAX_PER_DEPT}, "departments": {}}


def generate_for_department(dept_slug, dept, existing_bonus):
    core_titles = [a["title"] for a in dept["agents"]]
    bonus_titles = [p["title"] for p in existing_bonus]

    prompt = GENERATION_PROMPT.format(
        dept_name=dept["name"],
        existing_titles=", ".join(core_titles),
        bonus_titles=", ".join(bonus_titles) if bonus_titles else "(none yet)",
    )

    try:
        response = generate(prompt, chain="fast")
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            print(f"    No JSON found in response for {dept_slug}")
            return None

        data = json.loads(json_match.group())

        required = ["id", "title", "one_liner", "prompt", "deliverables", "tags"]
        for field in required:
            if field not in data:
                print(f"    Missing field '{field}' for {dept_slug}")
                return None

        slug = re.sub(r'[^\w\s-]', '', data["id"].lower())
        slug = re.sub(r'[\s_]+', '-', slug).strip('-')
        data["id"] = slug
        data["added_date"] = TODAY
        data["works_with"] = ["Claude", "GPT-4", "Gemini"]

        return data

    except Exception as e:
        print(f"    Generation failed for {dept_slug}: {e}")
        return None


def run(target_dept=None, dry_run=False):
    agents_data = load_agents_data()
    bonus_data = load_bonus_data()
    departments = agents_data["departments"]

    generated = 0
    rotated = 0

    for dept_slug, dept in departments.items():
        if target_dept and dept_slug != target_dept:
            continue

        existing_bonus = bonus_data["departments"].get(dept_slug, [])

        print(f"  [{dept_slug}] Generating bonus prompt ({len(existing_bonus)}/{MAX_PER_DEPT} existing)...")
        new_prompt = generate_for_department(dept_slug, dept, existing_bonus)

        if not new_prompt:
            continue

        if dry_run:
            print(f"    [DRY RUN] Would add: {new_prompt['title']}")
            print(f"    One-liner: {new_prompt['one_liner']}")
            print(f"    Tags: {', '.join(new_prompt['tags'])}")
            generated += 1
            continue

        if dept_slug not in bonus_data["departments"]:
            bonus_data["departments"][dept_slug] = []

        bonus_data["departments"][dept_slug].append(new_prompt)

        if len(bonus_data["departments"][dept_slug]) > MAX_PER_DEPT:
            removed = bonus_data["departments"][dept_slug].pop(0)
            print(f"    Rotated out: {removed['title']}")
            rotated += 1

        print(f"    Added: {new_prompt['title']}")
        generated += 1

        time.sleep(2)

    if not dry_run and generated > 0:
        bonus_data["meta"]["generated"] = TODAY
        bonus_data["meta"]["max_per_dept"] = MAX_PER_DEPT
        with open(BONUS_FILE, "w") as f:
            json.dump(bonus_data, f, indent=2)
        print(f"\nSaved {BONUS_FILE}")

    print(f"\nGenerated: {generated} prompts, Rotated: {rotated}")
    return generated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate weekly bonus prompt recipes")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--department", type=str, help="Generate for one department only")
    args = parser.parse_args()

    run(target_dept=args.department, dry_run=args.dry_run)
