"""Thread-safe ELM327 connection lifecycle and automatic reconnection."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import obd

from .config import Settings

logger = logging.getLogger(__name__)


class OBDConnectionError(RuntimeError):
    """Raised when the ELM327 adapter or vehicle ECU cannot be reached."""


class OBDCommunicationError(RuntimeError):
    """Raised when an established OBD-II exchange fails."""


ConnectionFactory = Callable[..., Any]


class ConnectionManager:
    """Own one python-OBD connection and serialize all adapter operations."""

    def __init__(self, settings: Settings, factory: ConnectionFactory = obd.OBD) -> None:
        self.settings = settings
        self._factory = factory
        self._connection: Any | None = None
        self._lock = threading.RLock()
        self._last_error: str | None = None
        self._supported_commands: frozenset[Any] = frozenset()

    @staticmethod
    def _is_connected(connection: Any | None) -> bool:
        if connection is None:
            return False
        try:
            status = connection.status()
            return status == obd.OBDStatus.CAR_CONNECTED or str(status).lower().endswith("car_connected")
        except Exception:
            return False

    def connect(self) -> bool:
        """Connect with bounded retries and cache the PIDs discovered by python-OBD."""
        with self._lock:
            if self._is_connected(self._connection):
                return True
            self._close_unlocked()
            for attempt in range(1, self.settings.reconnect_attempts + 1):
                try:
                    kwargs: dict[str, Any] = {
                        "baudrate": self.settings.baudrate,
                        "fast": self.settings.fast,
                        "timeout": self.settings.timeout,
                    }
                    self._connection = self._factory(self.settings.port, **kwargs)
                    if self._is_connected(self._connection):
                        self._supported_commands = frozenset(self._connection.supported_commands)
                        self._last_error = None
                        logger.info("OBD-II connected on %s", self.settings.port or "auto-detected port")
                        return True
                    self._last_error = "ELM327 found but no ECU connection (is ignition on?)"
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("OBD connection attempt %d failed: %s", attempt, self._last_error)
                self._close_unlocked()
                if attempt < self.settings.reconnect_attempts:
                    time.sleep(self.settings.reconnect_delay * attempt)
            return False

    def ensure_connected(self) -> Any:
        """Return a live connection, reconnecting first when required."""
        with self._lock:
            if not self._is_connected(self._connection) and not self.connect():
                raise OBDConnectionError(self._last_error or "OBD-II adapter is not connected")
            return self._connection

    def execute(self, operation: Callable[[Any], Any]) -> Any:
        """Execute an operation exclusively and retry once after a dropped connection."""
        with self._lock:
            connection = self.ensure_connected()
            try:
                result = operation(connection)
                if not self._is_connected(connection):
                    raise OBDCommunicationError("The ECU connection was lost during the request")
                return result
            except OBDCommunicationError:
                self._close_unlocked()
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self._close_unlocked()
            connection = self.ensure_connected()
            try:
                return operation(connection)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                raise OBDCommunicationError(f"OBD-II communication failed: {self._last_error}") from exc

    @property
    def supported_commands(self) -> frozenset[Any]:
        """Return the command set discovered during the latest connection."""
        with self._lock:
            self.ensure_connected()
            return self._supported_commands

    def status(self) -> dict[str, Any]:
        """Return adapter/ECU status without raising when connection is unavailable."""
        with self._lock:
            connected = self._is_connected(self._connection)
            raw_status = "not_connected"
            protocol: str | None = None
            if self._connection is not None:
                try:
                    raw_status = str(self._connection.status())
                    if connected:
                        protocol = str(self._connection.protocol_name())
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
            return {
                "connected": connected,
                "status": raw_status,
                "port": self.settings.port or "auto",
                "protocol": protocol,
                "supported_command_count": len(self._supported_commands),
                "last_error": self._last_error,
            }

    def close(self) -> None:
        """Close the serial connection and discard discovered capabilities."""
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                logger.debug("Ignoring error while closing OBD connection", exc_info=True)
        self._connection = None
        self._supported_commands = frozenset()

