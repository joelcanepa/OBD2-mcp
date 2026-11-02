"""In-process OBD-II simulator used when hardware is not available."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any

import obd


@dataclass(frozen=True)
class SimulatedQuantity:
    """Minimal Pint-compatible value consumed by the service serializer."""

    magnitude: int | float
    units: str


@dataclass(frozen=True)
class SimulatedStatus:
    """Minimal status value compatible with python-OBD's STATUS decoder."""

    MIL: bool
    DTC_count: int


@dataclass(frozen=True)
class SimulatedResponse:
    """Minimal response object compatible with python-OBD responses."""

    value: Any

    def is_null(self) -> bool:
        return self.value is None


class SimulatedConnection:
    """A deterministic, stateful stand-in for ``obd.OBD``."""

    SENSOR_NAMES = (
        "RPM",
        "SPEED",
        "COOLANT_TEMP",
        "ENGINE_LOAD",
        "THROTTLE_POS",
        "INTAKE_TEMP",
        "INTAKE_PRESSURE",
        "MAF",
        "FUEL_LEVEL",
        "CONTROL_MODULE_VOLTAGE",
        "RUN_TIME",
        "DISTANCE_W_MIL",
    )

    def __init__(self, *_: Any, **__: Any) -> None:
        self._closed = False
        self._sample = 0
        self._lock = threading.Lock()
        self._stored_dtcs = [
            ("P0113", "Intake Air Temperature Sensor Circuit High Input"),
        ]
        self._pending_dtcs = [
            ("P0300", "Random/Multiple Cylinder Misfire Detected"),
        ]
        command_names = (*self.SENSOR_NAMES, "GET_DTC", "GET_CURRENT_DTC", "CLEAR_DTC", "VIN", "STATUS")
        self.supported_commands = {
            obd.commands[name]
            for name in command_names
        }

    def status(self) -> Any:
        return obd.OBDStatus.NOT_CONNECTED if self._closed else obd.OBDStatus.CAR_CONNECTED

    def protocol_name(self) -> str:
        return "ISO 15765-4 (CAN 11/500) [simulation]"

    def close(self) -> None:
        self._closed = True

    def query(self, command: Any) -> SimulatedResponse:
        """Generate a plausible response for every advertised command."""
        if self._closed:
            return SimulatedResponse(None)

        with self._lock:
            self._sample += 1
            phase = self._sample / 4
            name = str(command.name)
            sensor_values: dict[str, SimulatedQuantity] = {
                "RPM": SimulatedQuantity(round(825 + 55 * math.sin(phase)), "revolutions_per_minute"),
                "SPEED": SimulatedQuantity(round(42 + 3 * math.sin(phase)), "kilometer_per_hour"),
                "COOLANT_TEMP": SimulatedQuantity(round(88 + math.sin(phase), 1), "degree_Celsius"),
                "ENGINE_LOAD": SimulatedQuantity(round(31 + 4 * math.sin(phase), 1), "percent"),
                "THROTTLE_POS": SimulatedQuantity(round(18 + 2 * math.sin(phase), 1), "percent"),
                "INTAKE_TEMP": SimulatedQuantity(round(27 + math.sin(phase), 1), "degree_Celsius"),
                "INTAKE_PRESSURE": SimulatedQuantity(round(43 + 2 * math.sin(phase)), "kilopascal"),
                "MAF": SimulatedQuantity(round(6.8 + 0.4 * math.sin(phase), 2), "gram_per_second"),
                "FUEL_LEVEL": SimulatedQuantity(round(64.0, 1), "percent"),
                "CONTROL_MODULE_VOLTAGE": SimulatedQuantity(round(14.1 + 0.1 * math.sin(phase), 2), "volt"),
                "RUN_TIME": SimulatedQuantity(1842 + self._sample, "second"),
                "DISTANCE_W_MIL": SimulatedQuantity(37, "kilometer"),
            }
            if name in sensor_values:
                return SimulatedResponse(sensor_values[name])
            if name == "GET_DTC":
                return SimulatedResponse(list(self._stored_dtcs))
            if name == "GET_CURRENT_DTC":
                return SimulatedResponse(list(self._pending_dtcs))
            if name == "CLEAR_DTC":
                self._stored_dtcs.clear()
                self._pending_dtcs.clear()
                return SimulatedResponse(None)
            if name == "VIN":
                return SimulatedResponse("SIMULATEDVIN00001")
            if name == "STATUS":
                count = len(self._stored_dtcs) + len(self._pending_dtcs)
                return SimulatedResponse(SimulatedStatus(MIL=count > 0, DTC_count=count))
            return SimulatedResponse(None)
