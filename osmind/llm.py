from __future__ import annotations

import json
import urllib.error
import urllib.request

from osmind.config import LLMConfig


class LLMError(Exception):
    pass


def chat_json(
    config: LLMConfig,
    system: str,
    user: str,
    *,
    timeout: int = 120,
    temperature: float = 0.4,
) -> dict:
    """One non-streaming chat call to an OpenAI-compatible endpoint, expecting a JSON object back."""
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    if config.enable_thinking:
        payload["chat_template_kwargs"] = {"enable_thinking": True}

    url = config.base_url.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "ignore")[:300]
        raise LLMError(f"LLM HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise LLMError(f"LLM unreachable: {error}") from error

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise LLMError(f"LLM response missing content: {body}") from error

    return _parse_json_object(content)


def _parse_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError(f"LLM did not return a JSON object: {content[:200]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise LLMError(f"LLM returned invalid JSON: {error}") from error
