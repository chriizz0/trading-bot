"""Minimale API-Clients (ohne Fremdpakete) für günstige Modelle. Schlüssel nur aus Umgebungsvariablen."""
from __future__ import annotations

import json
import os
import re
import urllib.request


def _post(url: str, headers: dict, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def ask_openai(prompt: str, model: str | None = None) -> str:
    model = model or os.environ.get("OPENAI_MODEL", "gpt-5")
    out = _post("https://api.openai.com/v1/chat/completions",
                {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                {"model": model, "messages": [{"role": "user", "content": prompt}]})
    return out["choices"][0]["message"]["content"]


def ask_anthropic(prompt: str, model: str | None = None, max_tokens: int = 4000) -> str:
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
    out = _post("https://api.anthropic.com/v1/messages",
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"},
                {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]})
    return "".join(b.get("text", "") for b in out["content"])


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    raw = m.group(1) if m else text[text.find("{") if "{" in text else text.find("["):]
    return json.loads(raw)
