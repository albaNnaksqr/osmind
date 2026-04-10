from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import yaml


class ConfigError(Exception):
    pass


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str


@dataclass
class AgentConfig:
    claude_code: str
    codex: str


@dataclass
class Config:
    interests: list[str]
    skills: list[str]
    resources: dict
    watching: list[dict]
    notes_vault: Path
    llm: LLMConfig
    external_agents: AgentConfig

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text())
        for field in ("interests", "skills", "watching", "notes_vault", "llm", "external_agents"):
            if field not in data:
                raise ConfigError(f"Missing required field: {field}")
        llm = data["llm"]
        agents = data["external_agents"]
        return cls(
            interests=data["interests"],
            skills=data["skills"],
            resources=data.get("resources", {}),
            watching=data["watching"],
            notes_vault=Path(data["notes_vault"]).expanduser(),
            llm=LLMConfig(
                base_url=llm["base_url"],
                model=llm["model"],
                api_key=llm.get("api_key", ""),
            ),
            external_agents=AgentConfig(
                claude_code=agents.get("claude_code", "claude"),
                codex=agents.get("codex", "codex"),
            ),
        )
