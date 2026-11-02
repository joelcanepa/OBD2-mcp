"""Interactive terminal client for validating the local OBD-II MCP server.

This program is an MCP client: it starts the server as a subprocess through
stdio and exercises the same protocol calls a desktop AI client would make.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult


def format_json(value: Any) -> str:
    """Format MCP/Pydantic values safely for a terminal."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def result_payload(result: CallToolResult) -> Any:
    """Prefer structured MCP output and otherwise return all content blocks."""
    if result.structuredContent is not None:
        return result.structuredContent
    return [
        block.model_dump(mode="json") if hasattr(block, "model_dump") else str(block)
        for block in result.content
    ]


async def prompt(message: str) -> str:
    """Read terminal input without blocking the MCP event loop."""
    return await asyncio.to_thread(input, message)


class TerminalTester:
    """Menu actions and result rendering for an initialized MCP client session."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def call(self, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        """Call one MCP tool and clearly display success, failure, and response."""
        print(f"\n-> MCP request: {tool_name}({format_json(arguments or {})})")
        try:
            result = await self.session.call_tool(tool_name, arguments)
        except Exception as exc:
            print(f"ERROR: Protocol/transport error: {type(exc).__name__}: {exc}")
            return
        outcome = "ERROR: MCP reported an error" if result.isError else "OK: MCP request succeeded"
        print(outcome)
        print("MCP server response:")
        print(format_json(result_payload(result)))

    async def list_tools(self) -> None:
        """Show tools actually advertised by the running server."""
        try:
            response = await self.session.list_tools()
        except Exception as exc:
            print(f"ERROR: Could not discover tools: {type(exc).__name__}: {exc}")
            return
        print("\nMCP tools discovered:")
        for tool in response.tools:
            print(f"- {tool.name}: {tool.description or '(no description)'}")

    async def read_sensors(self) -> None:
        """Ask for one or more sensor names and call read_sensor."""
        raw = await prompt("Comma-separated sensor names (e.g. RPM,SPEED): ")
        sensors = [item.strip() for item in raw.split(",") if item.strip()]
        if not sensors:
            print("ERROR: Enter at least one sensor.")
            return
        await self.call("read_sensor", {"sensors": sensors})

    async def clear_dtc(self) -> None:
        """Require an explicit terminal confirmation before requesting DTC deletion."""
        print("\nWARNING: This operation clears DTCs/freeze-frame and resets readiness monitors.")
        confirmation = await prompt("Type CLEAR to send confirm=true to the server: ")
        if confirmation != "CLEAR":
            print("Operation cancelled: no clear request was sent.")
            return
        await self.call("clear_dtc", {"confirm": True})

    async def smoke_test(self) -> None:
        """Run non-destructive checks useful immediately after connecting an adapter."""
        print("\n=== Non-destructive MCP/OBD-II connectivity test ===")
        for tool_name in ("get_connection_status", "list_supported_sensors", "get_vehicle_info", "read_dtc"):
            await self.call(tool_name)

    async def run_menu(self) -> None:
        """Keep the interactive menu open until the user exits."""
        actions: dict[str, Callable[[], Awaitable[None]]] = {
            "1": self.list_tools,
            "2": lambda: self.call("get_connection_status"),
            "3": lambda: self.call("list_supported_sensors"),
            "4": self.read_sensors,
            "5": lambda: self.call("read_dtc"),
            "6": lambda: self.call("get_vehicle_info"),
            "7": self.clear_dtc,
            "8": self.smoke_test,
        }
        while True:
            print(
                "\n=== OBD-II MCP Validator ===\n"
                "1. List tools advertised by the MCP server\n"
                "2. ELM327 / ECU connection status\n"
                "3. List supported sensors\n"
                "4. Read sensor(s)\n"
                "5. Read stored and pending DTCs\n"
                "6. Vehicle information (VIN / MIL)\n"
                "7. Clear DTCs (requires confirmation)\n"
                "8. Run the complete non-destructive test\n"
                "0. Exit"
            )
            choice = (await prompt("Option: ")).strip()
            if choice == "0":
                print("Test client finished.")
                return
            action = actions.get(choice)
            if action is None:
                print("ERROR: Invalid option.")
                continue
            await action()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the target server settings for the subprocess launched by this client."""
    parser = argparse.ArgumentParser(description="Interactive validation client for OBD-II MCP")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Server JSON file (default: ./config.json; auto-connect is used when absent)",
    )
    parser.add_argument("--port", help="Override the serial port in the configuration")
    parser.add_argument(
        "--simulation",
        action="store_true",
        help="Start the MCP server with generated OBD-II data and no vehicle connection",
    )
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> None:
    """Launch the local server, initialize MCP, and start the terminal UI."""
    server_args = ["-m", "obd_mcp.server"]
    if args.config.exists():
        server_args.extend(["--config", str(args.config.resolve())])
    elif args.config != Path("config.json"):
        raise FileNotFoundError(f"Configuration file does not exist: {args.config}")
    if args.port:
        server_args.extend(["--port", args.port])
    if args.simulation:
        server_args.append("--simulation")
    parameters = StdioServerParameters(command=sys.executable, args=server_args, cwd=Path.cwd())
    print(f"Starting MCP server: {sys.executable} {' '.join(server_args)}")
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            print(
                "MCP session initialized with: "
                f"{initialized.serverInfo.name} {initialized.serverInfo.version}"
            )
            await TerminalTester(session).run_menu()


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("\nTest client interrupted.")
    except Exception as exc:
        print(f"\nERROR: Could not start or negotiate MCP: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
