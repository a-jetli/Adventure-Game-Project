"""Runtime configuration for the LLM provider, read from the environment / .env.

Everything an end user needs to bring their own key, provider, or models lives
here. Copy `.env.example` to `.env` and edit it; no source changes required.
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

# Load .env here so config is correct no matter which entry point imports it.
load_dotenv()

# Credentials. LLM_API_KEY is preferred; OPENAI_API_KEY is still honored so
# existing setups keep working.
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

# Point this at any OpenAI-compatible endpoint to use a non-OpenAI provider
# (Google Gemini, OpenRouter, a local server, Anthropic's compat endpoint, ...).
# Leave unset for OpenAI itself.
BASE_URL = os.getenv("LLM_BASE_URL") or None

# Models. Defaults are the OpenAI models the game was tuned on.
MODEL_NARRATIVE = os.getenv("MODEL_NARRATIVE", "gpt-5.4-nano")
MODEL_SUMMARY = os.getenv("MODEL_SUMMARY", "gpt-4o-mini")

# Reasoning effort for the narrative model (OpenAI reasoning models only:
# low | medium | high). Set to "" or "none" to omit the parameter for providers
# or models that don't accept it.
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")


def reasoning_kwargs() -> dict:
    """The reasoning_effort kwarg to splat into a completions call, or {} when
    it should be omitted (non-OpenAI providers / non-reasoning models)."""
    if REASONING_EFFORT and REASONING_EFFORT.lower() != "none":
        return {"reasoning_effort": REASONING_EFFORT}
    return {}


def make_client() -> OpenAI:
    """An OpenAI-SDK client pointed at the configured provider."""
    kwargs = {"api_key": API_KEY}
    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    return OpenAI(**kwargs)
