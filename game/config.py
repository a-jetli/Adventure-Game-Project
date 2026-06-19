"""Runtime configuration for the LLM provider, read from the environment / .env.

Everything an end user needs to bring their own key, provider, or models lives
here. Copy `.env.example` to `.env` and edit it, or use the in-game first-run
setup which writes `.env` for you; no source changes required.
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

ENV_PATH = ".env"
_PLACEHOLDER_KEYS = {"", "your-api-key-here", "your-key-here", "sk-..."}

# Module globals, (re)populated by _read_env(). Other modules should read these
# off the `config` module (e.g. config.MODEL_NARRATIVE) so reload() takes effect.
API_KEY = None
BASE_URL = None
MODEL_NARRATIVE = "gpt-5.4-nano"
MODEL_SUMMARY = "gpt-4o-mini"
REASONING_EFFORT = "low"
UI_THEME = "dark"


def _read_env():
    global API_KEY, BASE_URL, MODEL_NARRATIVE, MODEL_SUMMARY, REASONING_EFFORT, UI_THEME
    API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    BASE_URL = os.getenv("LLM_BASE_URL") or None
    MODEL_NARRATIVE = os.getenv("MODEL_NARRATIVE", "gpt-5.4-nano")
    MODEL_SUMMARY = os.getenv("MODEL_SUMMARY", "gpt-4o-mini")
    REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")
    UI_THEME = os.getenv("UI_THEME", "dark")


# Load .env here so config is correct no matter which entry point imports it.
load_dotenv()
_read_env()


def reload():
    """Re-read .env (used after first-run setup writes it)."""
    load_dotenv(override=True)
    _read_env()


def needs_setup() -> bool:
    """True when there's no usable API key yet (fresh checkout / placeholder)."""
    return not API_KEY or API_KEY.strip() in _PLACEHOLDER_KEYS


def reasoning_kwargs() -> dict:
    """Returns {"reasoning_effort": ...} to add to a model call, or an empty {}
    when it shouldn't be sent at all (providers other than OpenAI, or models that
    don't do reasoning). The caller spreads it into the call with **."""
    if REASONING_EFFORT and REASONING_EFFORT.lower() != "none":
        return {"reasoning_effort": REASONING_EFFORT}
    return {}


def make_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    """An OpenAI-SDK client pointed at the configured provider. Optional
    overrides let a caller build a client before .env is reloaded."""
    kwargs = {"api_key": api_key or API_KEY}
    bu = base_url if base_url is not None else BASE_URL
    if bu:
        kwargs["base_url"] = bu
    return OpenAI(**kwargs)


# Provider presets for first-run setup. Each fills in the OpenAI-compatible
# endpoint and sensible default model names; the key is asked separately.
PROVIDER_PRESETS = {
    "openai": {
        "label": "OpenAI",
        "LLM_BASE_URL": "",
        "MODEL_NARRATIVE": "gpt-5.4-nano",
        "MODEL_SUMMARY": "gpt-4o-mini",
        "LLM_REASONING_EFFORT": "low",
    },
    "gemini": {
        "label": "Google Gemini",
        "LLM_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "MODEL_NARRATIVE": "gemini-2.0-flash",
        "MODEL_SUMMARY": "gemini-2.0-flash",
        "LLM_REASONING_EFFORT": "",
    },
    "openrouter": {
        "label": "OpenRouter",
        "LLM_BASE_URL": "https://openrouter.ai/api/v1",
        "MODEL_NARRATIVE": "openai/gpt-4o-mini",
        "MODEL_SUMMARY": "openai/gpt-4o-mini",
        "LLM_REASONING_EFFORT": "",
    },
    "ollama": {
        "label": "Local (Ollama)",
        "LLM_BASE_URL": "http://localhost:11434/v1",
        "MODEL_NARRATIVE": "llama3.1",
        "MODEL_SUMMARY": "llama3.1",
        "LLM_REASONING_EFFORT": "",
    },
}


def write_env(updates: dict):
    """Merge key=value updates into .env, preserving existing lines/comments."""
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            lines = f.read().splitlines()
    out, seen = [], set()
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in updates:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    with open(ENV_PATH, "w") as f:
        f.write("\n".join(out) + "\n")
