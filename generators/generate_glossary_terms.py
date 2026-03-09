#!/usr/bin/env python3
"""Generate weekly glossary terms for the AI Agent Library.

Generates N new terms per run (default 5), avoiding duplicates with existing
terms. Terms are appended to glossary_data.json and meta is updated.

Usage:
    python generate_glossary_terms.py               # generate 5 terms
    python generate_glossary_terms.py --dry-run      # preview without writing
    python generate_glossary_terms.py --count=10     # generate 10 terms
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
GLOSSARY_FILE = AGENTS_DIR / "glossary_data.json"

VALID_CATEGORIES = ["concepts", "techniques", "infrastructure", "models", "security"]
TODAY = date.today().isoformat()

GENERATION_PROMPT = """You are adding a new term to an AI/ML glossary used by working professionals — founders, engineers, and operators who are building or managing AI systems.

TONE: Plain English, never academic. Use analogies. Match this style exactly:
- Fine-Tuning: "Like teaching a general-purpose chef to specialize in Italian cuisine."
- Context Window: "Think of it as the model's working memory."
- Hallucination: "It doesn't 'know' it's making things up — it's pattern-matching, not fact-checking."
- Token: "A token is roughly 3/4 of a word. 'Hamburger' is 3 tokens."

Definitions should be 2-4 sentences. Direct, practical, memorable. No fluff.

CATEGORIES (pick exactly one):
- concepts — fundamental AI ideas every practitioner should know
- techniques — methods and patterns for using AI effectively
- infrastructure — APIs, servers, databases, deployment tools
- models — neural network architectures, training approaches, model types
- security — risks, attacks, defenses, safety patterns

EXISTING TERMS (do NOT generate duplicates):
{existing_terms}

Generate exactly ONE new glossary term that:
1. Is commonly encountered by AI professionals but not already in the list above
2. Has a plain-English definition with a concrete analogy or example
3. Belongs clearly to one of the 5 categories
4. Is NOT a brand name or company

Return ONLY a JSON object with these exact fields:
{{
  "id": "<kebab-case-slug>",
  "term": "<Term Name>",
  "aka": null or "<Full Name if the term is an acronym>",
  "definition": "<Plain-English definition, 2-4 sentences, with analogy or example>",
  "category": "<one of: concepts, techniques, infrastructure, models, security>"
}}

Return ONLY the JSON object. No explanation, no preamble, no trailing text."""


def load_glossary_data():
    if GLOSSARY_FILE.exists():
        with open(GLOSSARY_FILE) as f:
            return json.load(f)
    return {"meta": {"updated": TODAY, "count": 0}, "terms": []}


def sanitize_id(raw_id):
    slug = raw_id.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = slug.strip('-')
    return slug


def generate_term(existing_term_names):
    existing_list = "\n".join(f"- {name}" for name in sorted(existing_term_names))
    prompt = GENERATION_PROMPT.format(existing_terms=existing_list)

    try:
        response = generate(prompt, chain="fast")

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            print("    No JSON found in LLM response.")
            return None

        data = json.loads(json_match.group())

        required = ["id", "term", "aka", "definition", "category"]
        for field in required:
            if field not in data:
                print(f"    Missing field '{field}' in LLM response.")
                return None

        if data["category"] not in VALID_CATEGORIES:
            print(f"    Invalid category '{data['category']}' — skipping.")
            return None

        data["id"] = sanitize_id(data["id"])
        data["added_date"] = TODAY

        return data

    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"    Generation failed: {e}")
        return None


def run(count=5, dry_run=False):
    glossary = load_glossary_data()
    existing_terms = glossary.get("terms", [])

    existing_term_names = {t["term"].lower() for t in existing_terms}
    existing_ids = {t["id"] for t in existing_terms}

    generated = 0
    skipped = 0
    new_terms = []

    print(f"Generating {count} new glossary terms ({len(existing_terms)} existing)...")

    for i in range(count):
        print(f"\n  [{i + 1}/{count}] Requesting term from LLM...")

        all_known_names = existing_term_names | {t["term"].lower() for t in new_terms}
        term = generate_term(all_known_names)

        if not term:
            skipped += 1
            continue

        if term["id"] in existing_ids or term["term"].lower() in existing_term_names:
            print(f"    Duplicate detected: '{term['term']}' — skipping.")
            skipped += 1
            continue

        if dry_run:
            print(f"    [DRY RUN] Would add: {term['term']} ({term['category']})")
            print(f"    Definition: {term['definition'][:100]}...")
        else:
            print(f"    Added: {term['term']} ({term['category']})")

        new_terms.append(term)
        existing_ids.add(term["id"])
        generated += 1

        if i < count - 1:
            time.sleep(2)

    if not dry_run and new_terms:
        glossary["terms"].extend(new_terms)
        glossary["meta"]["updated"] = TODAY
        glossary["meta"]["count"] = len(glossary["terms"])

        with open(GLOSSARY_FILE, "w") as f:
            json.dump(glossary, f, indent=2)

        print(f"\nSaved {GLOSSARY_FILE}")
        print(f"Total terms: {glossary['meta']['count']}")

    print(f"\nGenerated: {generated}  Skipped/failed: {skipped}")
    return generated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate weekly AI glossary terms")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to disk")
    parser.add_argument("--count", type=int, default=5, help="Number of terms to generate (default: 5)")
    args = parser.parse_args()

    run(count=args.count, dry_run=args.dry_run)
