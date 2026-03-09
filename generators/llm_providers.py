"""Unified LLM provider module with fallback chains.

Five providers, three chains:
  - "morning": Cerebras -> Groq -> Gemini -> SambaNova -> CF Workers AI
  - "default": Groq -> Gemini -> Cerebras -> SambaNova -> CF Workers AI
  - "fast":    Cerebras -> Gemini -> SambaNova

All providers share retry logic for 429/rate-limit errors.

Setup:
  Copy .env.example to .env and add your API keys.
  You only need keys for the providers you want to use — the chain
  automatically skips providers with missing keys.
"""

import os
import time
from pathlib import Path
from dotenv import load_dotenv
import requests as _requests

# Load .env from this directory
load_dotenv(Path(__file__).resolve().parent / ".env")

# --- API keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY")
CF_AI_API_TOKEN = os.getenv("CF_AI_API_TOKEN")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")

# --- Model IDs ---
GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"
CEREBRAS_MODEL = "gpt-oss-120b"
SAMBANOVA_MODEL = "Meta-Llama-3.3-70B-Instruct"
CF_AI_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

# --- Gemini client (lazy init to avoid import-time crash if key missing) ---
_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    return _gemini_client


def _is_rate_limited(error):
    """Check if an error is a rate limit (429) error."""
    s = str(error)
    return "429" in s or "RESOURCE_EXHAUSTED" in s or "rate_limit" in s


def _is_daily_limit(error):
    """Check if error is a daily/quota limit (not just per-minute throttle)."""
    s = str(error)
    return "per day" in s or "TPD" in s or "daily" in s.lower()


# Track providers that hit daily limits — skip retries for the rest of this process
_exhausted_providers = set()


# --- Individual provider functions ---

def _groq_generate(prompt, max_tokens=4096):
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY, timeout=120)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def _gemini_generate(prompt, max_tokens=4096):
    client = _get_gemini_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
        config={"http_options": {"timeout": 120_000}},
    )
    return response.text


def _cerebras_generate(prompt, max_tokens=4096):
    from cerebras.cloud.sdk import Cerebras
    client = Cerebras(api_key=CEREBRAS_API_KEY, timeout=120)
    response = client.chat.completions.create(
        model=CEREBRAS_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def _sambanova_generate(prompt, max_tokens=4096):
    resp = _requests.post(
        "https://api.sambanova.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {SAMBANOVA_API_KEY}"},
        json={"model": SAMBANOVA_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _cf_ai_generate(prompt, max_tokens=4096):
    resp = _requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {CF_AI_API_TOKEN}"},
        json={"model": CF_AI_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _try_provider(name, func, prompt, max_tokens, retries=2):
    """Try a provider with retry on rate-limit errors.

    Skips providers that already hit their daily limit this session.
    On daily limit detection, marks provider as exhausted (no future retries).
    """
    if name in _exhausted_providers:
        return None
    for attempt in range(retries + 1):
        try:
            return func(prompt, max_tokens)
        except Exception as e:
            if _is_rate_limited(e):
                if _is_daily_limit(e):
                    print(f"  [LLM] {name} daily limit hit — skipping for rest of session")
                    _exhausted_providers.add(name)
                    return None
                if attempt < retries:
                    wait = 8 * (attempt + 1)
                    print(f"  [LLM] {name} rate-limited, retrying in {wait}s...")
                    time.sleep(wait)
                    continue
            print(f"  [LLM] {name} failed: {e}")
            return None
    return None


# --- Chain definitions ---

CHAINS = {
    "morning": [
        ("Cerebras", CEREBRAS_API_KEY, _cerebras_generate),
        ("Groq", GROQ_API_KEY, _groq_generate),
        ("Gemini", GEMINI_API_KEY, _gemini_generate),
        ("SambaNova", SAMBANOVA_API_KEY, _sambanova_generate),
        ("CF-AI", CF_AI_API_TOKEN, _cf_ai_generate),
    ],
    "default": [
        ("Groq", GROQ_API_KEY, _groq_generate),
        ("Gemini", GEMINI_API_KEY, _gemini_generate),
        ("Cerebras", CEREBRAS_API_KEY, _cerebras_generate),
        ("SambaNova", SAMBANOVA_API_KEY, _sambanova_generate),
        ("CF-AI", CF_AI_API_TOKEN, _cf_ai_generate),
    ],
    "fast": [
        ("Cerebras", CEREBRAS_API_KEY, _cerebras_generate),
        ("Gemini", GEMINI_API_KEY, _gemini_generate),
        ("SambaNova", SAMBANOVA_API_KEY, _sambanova_generate),
    ],
}


def generate(prompt, chain="default", max_tokens=4096):
    """Generate text using the specified fallback chain.

    Args:
        prompt: The prompt text.
        chain: "morning", "default", or "fast".
        max_tokens: Max tokens for response.

    Returns:
        Generated text string.

    Raises:
        Exception: If all providers fail.
    """
    providers = CHAINS.get(chain, CHAINS["default"])

    for name, api_key, func in providers:
        if not api_key:
            continue
        print(f"  [LLM] {name} ({get_model_name(name) or 'unknown'})")
        result = _try_provider(name, func, prompt, max_tokens)
        if result is not None:
            return result

    raise Exception(f"All LLM providers failed (chain={chain})")


def generate_grounded(prompt, retries=3):
    """Generate text with Gemini using Google Search grounding, with fallback to standard chain."""
    from google.genai import types
    client = _get_gemini_client()
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            )
            return response.text
        except Exception as e:
            if _is_rate_limited(e) and attempt < retries - 1:
                time.sleep(8 * (attempt + 1))
                continue
            print(f"  [LLM] Grounded Gemini failed: {e}, falling back to standard chain")
            return generate(prompt, chain="morning")


# --- Convenience for model name logging ---

def get_model_name(provider_name):
    """Get model ID for a provider name."""
    return {
        "Groq": GROQ_MODEL, "Gemini": GEMINI_MODEL, "Cerebras": CEREBRAS_MODEL,
        "SambaNova": SAMBANOVA_MODEL, "CF-AI": CF_AI_MODEL,
    }.get(provider_name)
