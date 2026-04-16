"""Runtime configuration for `agent-cli`.

Configuration sources (highest priority first):

1. Environment variables (`EXPERT_AGENT_ENDPOINT`, `EXPERT_AGENT_API_KEY`,
   `EXPERT_AGENT_TIMEOUT_SECONDS`).
2. `~/.config/expert-agent/config.toml` if present.
3. Built-in defaults.

Remote commands (`sync`, `ask`, `sessions`) require `endpoint` + `api_key`.
`init` / `validate` / `count-tokens` operate fully offline and do not need them.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def _user_config_path() -> Path:
    return Path.home() / ".config" / "expert-agent" / "config.toml"


def _load_toml_defaults() -> dict[str, Any]:
    path = _user_config_path()
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    # Accept both flat keys and an [expert_agent] section.
    section = raw.get("expert_agent") if isinstance(raw.get("expert_agent"), dict) else None
    data = section if section is not None else raw
    return {k: v for k, v in data.items() if isinstance(k, str)}


class CliConfig(BaseSettings):
    """Strongly-typed CLI configuration."""

    model_config = SettingsConfigDict(
        env_prefix="EXPERT_AGENT_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    endpoint: HttpUrl | None = Field(default=None, description="Base URL of the agent runtime.")
    api_key: str | None = Field(default=None, description="Admin bearer token for remote calls.")
    timeout_seconds: float = Field(default=120.0, ge=1.0, le=3_600.0)

    def require_remote(self) -> tuple[str, str]:
        """Return `(endpoint, api_key)`, raising a user-friendly error if missing."""
        if self.endpoint is None or not self.api_key:
            raise RemoteConfigError(
                "Remote endpoint is not configured. "
                "Set EXPERT_AGENT_ENDPOINT and EXPERT_AGENT_API_KEY, "
                "or add them to ~/.config/expert-agent/config.toml."
            )
        return str(self.endpoint).rstrip("/"), self.api_key


class RemoteConfigError(RuntimeError):
    """Raised when a remote-only command is invoked without the required config."""


@lru_cache(maxsize=1)
def get_config() -> CliConfig:
    """Return the cached `CliConfig` instance (env > TOML > defaults)."""
    toml_defaults = _load_toml_defaults()
    return CliConfig(**toml_defaults)


def make_http_client(
    *,
    endpoint: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
) -> httpx.AsyncClient:
    """Return an `httpx.AsyncClient` wired up with base_url + auth headers."""
    cfg = get_config()
    base_url = endpoint or (str(cfg.endpoint).rstrip("/") if cfg.endpoint else "")
    token = api_key or cfg.api_key or ""
    headers: dict[str, str] = {
        "User-Agent": "agent-cli",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=timeout if timeout is not None else cfg.timeout_seconds,
    )


__all__ = [
    "CliConfig",
    "RemoteConfigError",
    "get_config",
    "make_http_client",
]
