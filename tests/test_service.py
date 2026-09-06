from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import obd
import pytest

from obd_mcp.config import Settings
from obd_mcp.connection import ConnectionManager
from obd_mcp.obd_service import OBDService, UnsupportedCommandError


class Quantity:
    magnitude = 750
    units = "revolutions_per_minute"


class Status:
    MIL = True
    DTC_count = 1


@dataclass
class Response:
    value: Any

    def is_null(self) -> bool:
        return self.value is None


class FakeConnection:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.closed = False
        self.supported_commands = {
            obd.commands.RPM,
            obd.commands.GET_DTC,
            obd.commands.GET_CURRENT_DTC,
            obd.commands.CLEAR_DTC,
            obd.commands.VIN,
            obd.commands.STATUS,
        }

    def status(self) -> Any:
        return obd.OBDStatus.NOT_CONNECTED if self.closed else obd.OBDStatus.CAR_CONNECTED

    def protocol_name(self) -> str:
        return "ISO 15765-4 (CAN 11/500)"

    def close(self) -> None:
        self.closed = True

    def query(self, command: Any) -> Response:
        values = {
            "RPM": Quantity(),
            "GET_DTC": [("P0113", "Intake Air Temperature Sensor Circuit High")],
            "GET_CURRENT_DTC": [("P0300", "Random/Multiple Cylinder Misfire Detected")],
            "CLEAR_DTC": None,
            "VIN": "1M8GDM9AXKP042788",
            "STATUS": Status(),
        }
        return Response(values[command.name])


@pytest.fixture
def service() -> OBDService:
    manager = ConnectionManager(Settings(reconnect_delay=0), factory=FakeConnection)
    return OBDService(manager)


async def test_discovery_and_sensor_read(service: OBDService) -> None:
    sensors = await service.list_supported_sensors()
    assert sensors == [{"name": "RPM", "description": "Engine RPM"}]
    readings = await service.read_sensors(["rpm"])
    assert readings == [
        {"name": "RPM", "value": 750, "unit": "revolutions_per_minute"}
    ]


async def test_unsupported_sensor(service: OBDService) -> None:
    with pytest.raises(UnsupportedCommandError):
        await service.read_sensors(["SPEED"])


async def test_dtc_and_vehicle_info(service: OBDService) -> None:
    dtcs = await service.read_dtc()
    assert [item["status"] for item in dtcs] == ["stored", "pending/current_cycle"]
    info = await service.vehicle_info()
    assert info["vin"] == "1M8GDM9AXKP042788"
    assert info["mil_on"] is True
    assert info["dtc_count"] == 1


async def test_clear_dtc_treats_empty_decoder_as_success(service: OBDService) -> None:
    result = await service.clear_dtc()
    assert result["cleared"] is True

