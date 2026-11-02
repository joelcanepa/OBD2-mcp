from __future__ import annotations

from obd_mcp.config import Settings
from obd_mcp.connection import ConnectionManager
from obd_mcp.obd_service import OBDService
from obd_mcp.simulation import SimulatedConnection


def simulated_service() -> OBDService:
    settings = Settings(simulation=True, reconnect_delay=0)
    return OBDService(ConnectionManager(settings, factory=SimulatedConnection))


async def test_simulation_exposes_status_and_sensor_data() -> None:
    service = simulated_service()
    assert await service.connect() is True

    status = await service.connection_status()
    assert status["connected"] is True
    assert status["simulation"] is True
    assert status["port"] == "simulation"

    sensors = await service.list_supported_sensors()
    names = {sensor["name"] for sensor in sensors}
    assert {"RPM", "SPEED", "COOLANT_TEMP", "FUEL_LEVEL"} <= names

    readings = await service.read_sensors(["RPM", "SPEED"])
    assert [reading["name"] for reading in readings] == ["RPM", "SPEED"]
    assert all("value" in reading and "unit" in reading for reading in readings)


async def test_simulation_supports_vehicle_dtc_and_clear_operations() -> None:
    service = simulated_service()
    info = await service.vehicle_info()
    assert info["vin"] == "SIMULATEDVIN00001"
    assert info["mil_on"] is True
    assert info["dtc_count"] == 2
    assert len(await service.read_dtc()) == 2

    result = await service.clear_dtc()
    assert result["cleared"] is True
    assert await service.read_dtc() == []
    assert (await service.vehicle_info())["mil_on"] is False
