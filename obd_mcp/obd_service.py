"""High-level, JSON-safe OBD-II operations."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import obd

from .connection import ConnectionManager, OBDCommunicationError


class UnsupportedCommandError(ValueError):
    """Raised when a command is unknown or unsupported by the connected vehicle."""


class InvalidOBDResponseError(OBDCommunicationError):
    """Raised when the ECU returns no usable data."""


_NON_SENSOR_NAMES = {
    "PIDS_A", "PIDS_B", "PIDS_C", "PIDS_D", "PIDS_9A", "MIDS_A",
    "GET_DTC", "GET_CURRENT_DTC", "CLEAR_DTC", "STATUS", "FREEZE_DTC",
    "ELM_VERSION", "ELM_VOLTAGE", "VIN", "VIN_MESSAGE_COUNT",
    "CALIBRATION_ID", "CALIBRATION_ID_MESSAGE_COUNT", "CVN", "CVN_MESSAGE_COUNT",
}


def _command_name(command: Any) -> str:
    """Return a stable textual name for a python-OBD command."""
    return str(command.name)


def _json_value(value: Any) -> dict[str, Any]:
    """Convert Pint quantities and python-OBD values into JSON-safe fields."""
    if hasattr(value, "magnitude") and hasattr(value, "units"):
        magnitude = value.magnitude
        if hasattr(magnitude, "item"):
            magnitude = magnitude.item()
        return {"value": magnitude, "unit": str(value.units)}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return {"value": value, "unit": None}
    if isinstance(value, tuple):
        return {"value": list(value), "unit": None}
    if isinstance(value, list):
        return {"value": value, "unit": None}
    return {"value": str(value), "unit": None}


class OBDService:
    """Expose asynchronous, JSON-safe use cases over the synchronous driver.

    Each public coroutine moves blocking serial work to a worker thread. The
    injected :class:`ConnectionManager` remains responsible for serialization,
    reconnection, and connection ownership.

    Args:
        manager: Shared connection manager for this service instance.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self.manager = manager

    async def connect(self) -> bool:
        """Open the OBD-II connection without blocking the event loop."""
        return await asyncio.to_thread(self.manager.connect)

    async def close(self) -> None:
        """Close the underlying connection without blocking the event loop."""
        await asyncio.to_thread(self.manager.close)

    async def connection_status(self) -> dict[str, Any]:
        """Attempt connection and return a JSON-safe status snapshot."""
        await asyncio.to_thread(self.manager.connect)
        return await asyncio.to_thread(self.manager.status)

    def _list_sensors_sync(self) -> list[dict[str, str]]:
        """Build the sorted sensor catalog from discovered OBD commands."""
        commands = self.manager.supported_commands
        sensors = [
            {"name": _command_name(cmd), "description": str(cmd.desc)}
            for cmd in commands
            if _command_name(cmd) not in _NON_SENSOR_NAMES
            and not _command_name(cmd).startswith("DTC_")
        ]
        return sorted(sensors, key=lambda item: item["name"])

    async def list_supported_sensors(self) -> list[dict[str, str]]:
        """Return live-data commands advertised by the connected vehicle."""
        return await asyncio.to_thread(self._list_sensors_sync)

    def _resolve_sensor(self, name: str) -> Any:
        """Resolve and validate a user-provided sensor name.

        Raises:
            UnsupportedCommandError: If the name is unknown, is not a sensor,
                or was not advertised by the current vehicle.
        """
        normalized = name.strip().upper()
        try:
            command = obd.commands[normalized]
        except (KeyError, AttributeError):
            raise UnsupportedCommandError(f"Unknown sensor: {name!r}") from None
        if command not in self.manager.supported_commands or normalized in _NON_SENSOR_NAMES:
            raise UnsupportedCommandError(f"Sensor {normalized!r} is not supported by this vehicle")
        return command

    def _read_sensors_sync(self, names: list[str]) -> list[dict[str, Any]]:
        """Read a batch of sensors in one serialized connection operation."""
        if not names:
            raise ValueError("At least one sensor name is required")
        commands = [(name.strip().upper(), self._resolve_sensor(name)) for name in names]

        def read_all(connection: Any) -> list[dict[str, Any]]:
            output: list[dict[str, Any]] = []
            for name, command in commands:
                response = connection.query(command)
                if response is None or response.is_null():
                    output.append({"name": name, "error": "ECU returned no data"})
                    continue
                output.append({"name": name, **_json_value(response.value)})
            return output

        return cast(list[dict[str, Any]], self.manager.execute(read_all))

    async def read_sensors(self, names: list[str]) -> list[dict[str, Any]]:
        """Read sensor names and return values, units, or per-sensor errors.

        Raises:
            ValueError: If ``names`` is empty.
            UnsupportedCommandError: If any requested sensor is unavailable.
        """
        return await asyncio.to_thread(self._read_sensors_sync, names)

    @staticmethod
    def _parse_dtc_response(response: Any, kind: str) -> list[dict[str, str]]:
        """Normalize one python-OBD DTC response into JSON-safe records."""
        if response is None or response.is_null() or not response.value:
            return []
        return [
            {"code": str(code), "description": str(description), "status": kind}
            for code, description in response.value
        ]

    def _read_dtc_sync(self) -> list[dict[str, str]]:
        def query(connection: Any) -> list[dict[str, str]]:
            dtcs: list[dict[str, str]] = []
            supported = self.manager.supported_commands
            for command, kind in (
                (obd.commands.GET_DTC, "stored"),
                (obd.commands.GET_CURRENT_DTC, "pending/current_cycle"),
            ):
                if command in supported:
                    dtcs.extend(self._parse_dtc_response(connection.query(command), kind))
            return dtcs

        return cast(list[dict[str, str]], self.manager.execute(query))

    async def read_dtc(self) -> list[dict[str, str]]:
        """Return stored and pending/current-cycle diagnostic codes."""
        return await asyncio.to_thread(self._read_dtc_sync)

    def _clear_dtc_sync(self) -> dict[str, Any]:
        if obd.commands.CLEAR_DTC not in self.manager.supported_commands:
            raise UnsupportedCommandError("CLEAR_DTC is not supported by this connection")

        def clear(connection: Any) -> dict[str, Any]:
            response = connection.query(obd.commands.CLEAR_DTC)
            if response is None:
                raise InvalidOBDResponseError("No response while clearing DTCs")
            return {
                "cleared": True,
                "message": "Clear command sent successfully; verify by reading DTCs again",
            }

        return cast(dict[str, Any], self.manager.execute(clear))

    async def clear_dtc(self) -> dict[str, Any]:
        """Send the destructive ECU command that clears diagnostic codes.

        Confirmation is enforced by the MCP boundary, not by this lower-level
        service method.
        """
        return await asyncio.to_thread(self._clear_dtc_sync)

    def _vehicle_info_sync(self) -> dict[str, Any]:
        def query(connection: Any) -> dict[str, Any]:
            supported = self.manager.supported_commands
            result: dict[str, Any] = {"vin": None, "mil_on": None, "dtc_count": None}
            if obd.commands.VIN in supported:
                response = connection.query(obd.commands.VIN)
                if response is not None and not response.is_null():
                    result["vin"] = str(response.value)
            if obd.commands.STATUS in supported:
                response = connection.query(obd.commands.STATUS)
                if response is not None and not response.is_null():
                    status = response.value
                    result["mil_on"] = bool(getattr(status, "MIL", False))
                    result["dtc_count"] = int(getattr(status, "DTC_count", 0))
            result["protocol"] = str(connection.protocol_name())
            return result

        return cast(dict[str, Any], self.manager.execute(query))

    async def vehicle_info(self) -> dict[str, Any]:
        """Return available VIN, MIL, DTC-count, and protocol information."""
        return await asyncio.to_thread(self._vehicle_info_sync)
