from __future__ import annotations
from openai import OpenAI
from osmind.config import LLMConfig


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self._client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
        self._model = cfg.model
        self._enable_thinking = cfg.enable_thinking

    def chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        kwargs: dict = {}
        if not self._enable_thinking:
            # Disable CoT for reasoning models (Qwen3, DeepSeek-R1, etc.)
            # so the response goes directly to content, not reasoning field
            kwargs["extra_body"] = {"enable_thinking": False}

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            **kwargs,
        )
        msg = resp.choices[0].message
        content = (msg.content or "").strip()
        if not content:
            # Fallback: reasoning model exhausted tokens before producing content
            content = (getattr(msg, "reasoning", None) or "").strip()
        return content
