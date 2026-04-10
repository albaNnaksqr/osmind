from __future__ import annotations
from openai import OpenAI
from osmind.config import LLMConfig


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self._client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
        self._model = cfg.model

    def chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
