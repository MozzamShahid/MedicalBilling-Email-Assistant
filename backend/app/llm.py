"""Which LLM provider to call: OpenRouter or the DeepSeek API directly.

Set LLM_PROVIDER=deepseek and DEEPSEEK_API_KEY in .env to skip OpenRouter.
Model names in .env stay the same (e.g. deepseek/deepseek-v4-flash)."""

import os

import requests


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "openrouter").strip().lower()


def _bare(model: str) -> str:
    return model.split("/", 1)[1] if model.startswith("deepseek/") else model


def litellm_model(env_var: str, default: str) -> str:
    """Model id in the form CrewAI/LiteLLM expects."""
    model = os.getenv(env_var, default)
    if provider() == "deepseek":
        return f"deepseek/{_bare(model)}"  # LiteLLM reads DEEPSEEK_API_KEY
    return f"openrouter/{model}"


def chat(payload: dict, timeout: int = 90) -> dict:
    """POST an OpenAI-style chat completion to the configured provider."""
    if provider() == "deepseek":
        url = "https://api.deepseek.com/chat/completions"
        key = os.environ["DEEPSEEK_API_KEY"]
        payload = {**payload, "model": _bare(payload["model"])}
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        key = os.environ["OPENROUTER_API_KEY"]
    resp = requests.post(
        url, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=timeout
    )
    resp.raise_for_status()
    return resp.json()
