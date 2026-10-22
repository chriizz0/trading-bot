"""Minimale API-Clients (ohne Fremdpakete) für günstige Modelle. Schlüssel nur aus Umgebungsvariablen."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    """Fehlermeldung ohne Header/Schlüssel – darf geloggt werden."""


def _post(url: str, headers: dict, body: dict) -> dict:
    headers = {k: v.strip() for k, v in headers.items()}  # Zeilenumbruch aus kopierten Schlüsseln entfernen
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={**headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code} von {url.split('/')[2]}: {e.read()[:300].decode('utf-8', 'replace')}") from None
    except Exception as e:  # noqa: BLE001 – niemals die Original-Meldung (kann Header enthalten) weitergeben
        raise LLMError(f"{type(e).__name__} beim Aufruf von {url.split('/')[2]}") from None


def ask_openai(prompt: str, model: str | None = None) -> str:
    model = model or os.environ.get("OPENAI_MODEL", "gpt-6-astra")
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
    """JSON aus einer Modellantwort holen – auch mit Codeblock, Vor-/Nachtext oder abgeschnittenem Ende."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    a, b = text.find("{"), text.rfind("}")
    if a < 0:
        raise ValueError("kein JSON in der Antwort")
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return json.JSONDecoder().raw_decode(text[a:])[0]
