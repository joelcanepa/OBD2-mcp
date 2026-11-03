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
    """Store validated runtime settings.

    Values are merged by :func:`load_settings`; constructing this class directly
    still applies the range checks in :meth:`__post_init__`.

    Attributes:
        port: Serial port used by the ELM327, or ``None`` for auto-detection.
        baudrate: Explicit serial speed, or ``None`` for driver detection.
        timeout: Maximum number of seconds allowed for adapter operations.
        fast: Whether python-OBD may skip conservative initialization steps.
        reconnect_attempts: Maximum attempts in one connection cycle.
        reconnect_delay: Base delay used by the linear retry backoff.
        transport: MCP transport exposed by the server.
        host: Bind address used by the HTTP transport.
        http_port: TCP port used by the HTTP transport.
        log_level: Python logging level name.
        simulation: Whether to replace the hardware driver with the simulator.
    """

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
    simulation: bool = False

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
    "OBD_SIMULATION": "simulation",
}


def _coerce(name: str, value: Any) -> Any:
    """Convert a configuration value to the type expected by ``Settings``.

    Args:
        name: Name of the destination setting.
        value: Raw value read from JSON, the environment, or a CLI override.

    Returns:
        The converted value. Unknown setting names are returned unchanged.

    Raises:
        ConfigurationError: If a textual Boolean is not recognized.
        ValueError: If a numeric value cannot be converted.
    """
    if value is None:
        return None
    if name in {"baudrate", "reconnect_attempts", "http_port"}:
        return int(value)
    if name in {"timeout", "reconnect_delay"}:
        return float(value)
    if name in {"fast", "simulation"} and isinstance(value, str):
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
    """Load and validate settings from every supported source.

    Precedence is ``overrides > environment > JSON > defaults``. An override
    whose value is ``None`` is ignored, which lets argparse distinguish between
    an omitted option and a deliberate false-y value.

    Args:
        config_path: Optional JSON configuration file.
        environ: Environment mapping; defaults to :data:`os.environ`.
        overrides: Usually command-line values keyed by setting name.

    Returns:
        A validated, immutable :class:`Settings` instance.

    Raises:
        ConfigurationError: If the file is unreadable, malformed, contains an
            unknown key, or selects an unsupported transport.
    """
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
    """Parse command-line arguments and merge all configuration sources.

    Args:
        argv: Arguments without the executable name. Uses ``sys.argv`` when
            omitted.

    Returns:
        A pair containing the merged settings and raw argparse namespace.
    """
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
    parser.add_argument(
        "--simulation",
        "-simulation",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use generated OBD-II data without connecting to an ELM327 adapter",
    )
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
        "simulation": args.simulation,
    }
    return load_settings(args.config, overrides=overrides), args
