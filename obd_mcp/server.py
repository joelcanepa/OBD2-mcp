"""FastMCP entry point and OBD-II tool definitions."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings, parse_args
from .connection import ConnectionManager
from .obd_service import OBDService
from .simulation import SimulatedConnection

logger = logging.getLogger(__name__)


def create_server(settings: Settings | None = None) -> FastMCP:
    """Build an independently testable MCP server instance.

    Args:
        settings: Runtime configuration. Defaults are loaded when omitted.

    Returns:
        A configured FastMCP application with six OBD-II tools.

    Note:
        The application lifespan owns connection startup and shutdown. Failure
        to connect during startup is non-fatal because each tool retries later.
    """
    current = settings or load_settings()
    factory = SimulatedConnection if current.simulation else None
    manager = ConnectionManager(current) if factory is None else ConnectionManager(current, factory=factory)
    service = OBDService(manager)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[None]:
        try:
            connected = await service.connect()
            if not connected:
                logger.warning("Server started without an ECU; tools will retry on demand")
            elif current.simulation:
                logger.info("OBD-II simulation mode is active; no vehicle connection is being used")
            yield
        finally:
            await service.close()

    app = FastMCP(
        "OBD-II ELM327",
        instructions=(
            "Read diagnostics from the locally connected vehicle. Call "
            "list_supported_sensors before read_sensor. Never clear DTCs without explicit user consent."
        ),
        lifespan=lifespan,
        host=current.host,
        port=current.http_port,
    )

    @app.tool()
    async def get_connection_status() -> dict[str, Any]:
        """Check the ELM327/ECU connection, port, and OBD-II protocol.

        Use this first when a vehicle may be off or disconnected.
        """
        return await service.connection_status()

    @app.tool()
    async def list_supported_sensors() -> list[dict[str, str]]:
        """List live sensor PIDs discovered as supported by the vehicle.

        Use these exact names with read_sensor.
        """
        return await service.list_supported_sensors()

    @app.tool()
    async def read_sensor(sensors: str | list[str]) -> list[dict[str, Any]]:
        """Read one or several supported sensors and return values with units.

        Examples: RPM, SPEED, COOLANT_TEMP, INTAKE_PRESSURE.
        """
        names = [sensors] if isinstance(sensors, str) else sensors
        return await service.read_sensors(names)

    @app.tool()
    async def read_dtc() -> dict[str, Any]:
        """Read stored and pending/current-cycle diagnostic trouble codes.

        Includes python-OBD technical descriptions when known and does not modify the ECU.
        """
        codes = await service.read_dtc()
        return {"count": len(codes), "dtcs": codes}

    @app.tool()
    async def clear_dtc(confirm: bool = False) -> dict[str, Any]:
        """Clear ECU DTCs and freeze-frame only after explicit user approval.

        Set confirm=true; this may reset readiness monitors and temporarily turn off the MIL.
        """
        if not confirm:
            return {
                "cleared": False,
                "confirmation_required": True,
                "message": "DTCs were not cleared. Obtain explicit user consent and retry with confirm=true.",
            }
        return await service.clear_dtc()

    @app.tool()
    async def get_vehicle_info() -> dict[str, Any]:
        """Read VIN, Check Engine/MIL state, DTC count, and OBD-II protocol."""
        return await service.vehicle_info()

    return app


mcp = create_server()


def main() -> None:
    """Load configuration, initialize logging, and run the selected transport."""
    settings, _ = parse_args()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = create_server(settings)
    if settings.transport == "streamable-http":
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
