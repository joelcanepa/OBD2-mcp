"""Convenience entry point for `python server.py`."""

from obd_mcp.server import main, mcp

__all__ = ["main", "mcp"]

if __name__ == "__main__":
    main()

