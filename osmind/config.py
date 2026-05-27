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
    enable_thinking: bool = False  # set True for reasoning models that need CoT


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
    output_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.output_dir is None:
            self.output_dir = self.notes_vault

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text())
        for field in ("interests", "skills", "watching", "llm", "external_agents"):
            if field not in data:
                raise ConfigError(f"Missing required field: {field}")
        output_dir_raw = data.get("output_dir") or data.get("notes_vault")
        if not output_dir_raw:
            raise ConfigError("Missing required field: output_dir")
        output_dir = Path(output_dir_raw).expanduser()
        llm = data["llm"]
        agents = data["external_agents"]
        return cls(
            interests=data["interests"],
            skills=data["skills"],
            resources=data.get("resources", {}),
            watching=data["watching"],
            notes_vault=output_dir,
            llm=LLMConfig(
                base_url=llm["base_url"],
                model=llm["model"],
                api_key=llm.get("api_key", ""),
                enable_thinking=llm.get("enable_thinking", False),
            ),
            external_agents=AgentConfig(
                claude_code=agents.get("claude_code", "claude"),
                codex=agents.get("codex", "codex"),
            ),
            output_dir=output_dir,
        )
