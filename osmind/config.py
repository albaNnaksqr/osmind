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
    llm: LLMConfig | None = None
    external_agents: AgentConfig | None = None
    output_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.output_dir is None:
            self.output_dir = self.notes_vault

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text())
        for field in ("interests", "skills", "watching"):
            if field not in data:
                raise ConfigError(f"Missing required field: {field}")
        output_dir_raw = data.get("output_dir") or data.get("notes_vault")
        if not output_dir_raw:
            raise ConfigError("Missing required field: output_dir")
        output_dir = Path(output_dir_raw).expanduser()
        llm_data = data.get("llm")
        llm = (
            LLMConfig(
                base_url=llm_data["base_url"],
                model=llm_data["model"],
                api_key=llm_data.get("api_key", ""),
                enable_thinking=llm_data.get("enable_thinking", False),
            )
            if llm_data
            else None
        )
        agents_data = data.get("external_agents")
        agents = (
            AgentConfig(
                claude_code=agents_data.get("claude_code", "claude"),
                codex=agents_data.get("codex", "codex"),
            )
            if agents_data
            else None
        )
        return cls(
            interests=data["interests"],
            skills=data["skills"],
            resources=data.get("resources", {}),
            watching=data["watching"],
            notes_vault=output_dir,
            llm=llm,
            external_agents=agents,
            output_dir=output_dir,
        )
