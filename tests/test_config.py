from __future__ import annotations

import json

import pytest

from obd_mcp.config import ConfigurationError, load_settings, parse_args


def test_precedence_cli_environment_json(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": "COM1", "timeout": 10}), encoding="utf-8")
    settings = load_settings(
        path,
        environ={"OBD_PORT": "COM2", "OBD_FAST": "true"},
        overrides={"port": "COM3"},
    )
    assert settings.port == "COM3"
    assert settings.timeout == 10
    assert settings.fast is True


def test_invalid_boolean_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        load_settings(environ={"OBD_FAST": "sometimes"})


def test_simulation_can_be_enabled_from_cli_or_environment() -> None:
    cli_settings, _ = parse_args(["--simulation"])
    assert cli_settings.simulation is True
    assert load_settings(environ={"OBD_SIMULATION": "true"}).simulation is True

