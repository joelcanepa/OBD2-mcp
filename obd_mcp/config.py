"""Configuration loading for the OBD-II MCP server."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast


class ConfigurationError(ValueError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings, populated from JSON, environment, and CLI options."""

    port: str | None = None
    baudrate: int | None = None
    timeout: float = 30.0
    fast: bool = False
    reconnect_attempts: int = 3
    reconnect_delay: float = 2.0
    transport: Literal["stdio", "streamable-http"] = "stdio"
    host: str = "127.0.0.1"
    http_port: int = 8000
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ConfigurationError("timeout must be greater than zero")
        if self.reconnect_attempts < 1:
            raise ConfigurationError("reconnect_attempts must be at least 1")
        if self.reconnect_delay < 0:
            raise ConfigurationError("reconnect_delay cannot be negative")
        if not 1 <= self.http_port <= 65535:
            raise ConfigurationError("http_port must be between 1 and 65535")


_ENV_MAP = {
    "OBD_PORT": "port",
    "OBD_BAUDRATE": "baudrate",
    "OBD_TIMEOUT": "timeout",
    "OBD_FAST": "fast",
    "OBD_RECONNECT_ATTEMPTS": "reconnect_attempts",
    "OBD_RECONNECT_DELAY": "reconnect_delay",
    "OBD_MCP_TRANSPORT": "transport",
    "OBD_MCP_HOST": "host",
    "OBD_MCP_HTTP_PORT": "http_port",
    "OBD_MCP_LOG_LEVEL": "log_level",
}


def _coerce(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in {"baudrate", "reconnect_attempts", "http_port"}:
        return int(value)
    if name in {"timeout", "reconnect_delay"}:
        return float(value)
    if name == "fast" and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
            raise ConfigurationError(f"Invalid boolean value for {name}: {value!r}")
        return normalized in {"1", "true", "yes", "on"}
    return value


def load_settings(
    config_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Load settings with precedence CLI overrides > environment > JSON > defaults."""
    values: dict[str, Any] = asdict(Settings())
    if config_path is not None:
        path = Path(config_path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Cannot read configuration {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigurationError("The JSON configuration root must be an object")
        unknown = set(raw) - set(values)
        if unknown:
            raise ConfigurationError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
        values.update(raw)

    env = os.environ if environ is None else environ
    for env_name, setting_name in _ENV_MAP.items():
        if env_name in env:
            values[setting_name] = env[env_name]
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    values = {name: _coerce(name, value) for name, value in values.items()}
    if values["transport"] not in {"stdio", "streamable-http"}:
        raise ConfigurationError("transport must be 'stdio' or 'streamable-http'")
    values["transport"] = cast(Literal["stdio", "streamable-http"], values["transport"])
    return Settings(**values)


def parse_args(argv: list[str] | None = None) -> tuple[Settings, argparse.Namespace]:
    """Parse server command-line arguments and return merged settings."""
    parser = argparse.ArgumentParser(description="MCP server for ELM327 OBD-II adapters")
    parser.add_argument("--config", help="Path to a JSON configuration file")
    parser.add_argument("--port", help="Serial port; omit for python-OBD auto-connect")
    parser.add_argument("--baudrate", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--fast", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--reconnect-attempts", type=int)
    parser.add_argument("--reconnect-delay", type=float)
    parser.add_argument("--transport", choices=("stdio", "streamable-http"))
    parser.add_argument("--host")
    parser.add_argument("--http-port", type=int)
    parser.add_argument("--log-level")
    args = parser.parse_args(argv)
    overrides = {
        "port": args.port,
        "baudrate": args.baudrate,
        "timeout": args.timeout,
        "fast": args.fast,
        "reconnect_attempts": args.reconnect_attempts,
        "reconnect_delay": args.reconnect_delay,
        "transport": args.transport,
        "host": args.host,
        "http_port": args.http_port,
        "log_level": args.log_level,
    }
    return load_settings(args.config, overrides=overrides), args
