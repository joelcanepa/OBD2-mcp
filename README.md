# OBD-II MCP Server

A local Python MCP server that lets an AI client read OBD-II diagnostics from a vehicle through a paired ELM327 Bluetooth adapter.

## What it does

The server exposes six MCP tools:

- `get_connection_status` — ELM327/ECU status, serial port, and negotiated protocol.
- `list_supported_sensors` — the live PIDs supported by the connected vehicle.
- `read_sensor` — one or more supported sensor values with units.
- `read_dtc` — stored and pending/current-cycle DTCs.
- `clear_dtc` — clears DTCs only when called with `confirm: true`.
- `get_vehicle_info` — VIN (when supported), MIL status, DTC count, and protocol.

`python-obd` discovers the vehicle's supported PID blocks at connection time. The server publishes only sensors found in those blocks, serializes access to the COM port, and reconnects once after a communication failure.

## Requirements

- Python 3.10 or newer.
- An OBD-II-compatible vehicle, with ignition in the **ON** position (and engine running if required by the vehicle).
- A classic Bluetooth ELM327 adapter that provides a Serial Port Profile (SPP).
- On Windows, a Bluetooth **outgoing** COM port assigned to the adapter.

BLE-only adapters frequently do not provide a serial port and cannot be used directly with `python-obd`.

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

Edit `config.json` and set `port` to the adapter's outgoing COM port:

```json
{
  "port": "COM3",
  "baudrate": null,
  "timeout": 30.0,
  "fast": false,
  "reconnect_attempts": 3,
  "reconnect_delay": 2.0,
  "transport": "stdio",
  "host": "127.0.0.1",
  "http_port": 8000,
  "log_level": "INFO"
}
```

`fast: false` and a 30-second timeout are more tolerant of Bluetooth ELM327 clones. Configuration precedence is: command line > environment variables > JSON file > defaults.

| Environment variable | Example |
| --- | --- |
| `OBD_PORT` | `COM3` or `/dev/rfcomm0` |
| `OBD_BAUDRATE` | `38400` |
| `OBD_TIMEOUT` | `30` |
| `OBD_FAST` | `false` |
| `OBD_RECONNECT_ATTEMPTS` | `3` |
| `OBD_RECONNECT_DELAY` | `2` |
| `OBD_MCP_TRANSPORT` | `stdio` or `streamable-http` |
| `OBD_MCP_HOST`, `OBD_MCP_HTTP_PORT` | `127.0.0.1`, `8000` |

## Windows Bluetooth setup

1. Park safely, turn the ignition to **ON**, and plug the ELM327 into the vehicle's OBD-II port.
2. In **Settings > Bluetooth & devices**, pair the adapter (`OBDII`, `ELM327`, etc.). Common PINs are `1234` and `0000`; prefer the manufacturer's PIN.
3. In **More Bluetooth settings > COM Ports** or Device Manager, identify the adapter's **outgoing** COM port (for example, `COM8`).
4. Put that exact value in `config.json`, for example: `"port": "COM8"`.
5. Close any diagnostic app that might have the COM port open.

## Connect ChatGPT through Streamable HTTP

Use this option when the MCP configuration screen accepts a server URL.

1. Complete the Bluetooth setup above and save the correct COM port in `config.json`.
2. Start **one** terminal in the project directory and run:

   ```powershell
   .venv\Scripts\python.exe -m obd_mcp.server --config config.json --transport streamable-http
   ```

3. Leave that terminal open. It is the MCP server process; do **not** run `server.py` separately.
4. In ChatGPT, add the MCP server URL:

   ```text
   http://127.0.0.1:8000/mcp
   ```

5. Leave the Bearer-token field empty and do not add custom headers. This local server does not implement authentication.
6. After connecting, start with `get_connection_status`. Then call `list_supported_sensors` before `read_sensor`.

The server attempts to connect to the ECU when it starts. If the vehicle or adapter is temporarily unavailable, the tools retry when called.

`127.0.0.1` means only this computer can reach the server. Do not expose it to your LAN or the public internet without adding authentication and network controls, especially because `clear_dtc` is destructive.

## Other ways to run it

### Stdio

Use this when the MCP client launches local commands itself:

```powershell
.venv\Scripts\python.exe -m obd_mcp.server --config config.json
```

For example, a desktop MCP client may use this Windows configuration:

```json
{
  "mcpServers": {
    "obd2": {
      "command": "C:\\path\\to\\OBD2-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "obd_mcp.server", "--config", "C:\\path\\to\\OBD2-mcp\\config.json"]
    }
  }
}
```

### MCP Inspector

```powershell
.venv\Scripts\mcp.exe dev server.py
```

### Interactive validator

The validator starts a temporary **stdio** server process itself, negotiates MCP, and provides a menu of safe checks. Do not start the HTTP server for this command.

```powershell
.venv\Scripts\python.exe scripts\mcp_terminal_tester.py --config config.json
```

Option 8 runs a non-destructive connectivity check: connection status, supported sensors, vehicle information, and DTCs. Option 7 requires typing `CLEAR` before it sends `confirm: true`.

To override the serial port for one test:

```powershell
.venv\Scripts\python.exe scripts\mcp_terminal_tester.py --port COM8
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No ECU connection | Ignition is ON, adapter has power, and the configured outgoing COM port is correct. |
| Port cannot be opened | Close Torque, scan tools, terminal programs, or anything else using that COM port. |
| No serial port after pairing | The adapter may be BLE-only rather than Bluetooth SPP. |
| ChatGPT cannot connect | Confirm the server terminal is still running and the URL is exactly `http://127.0.0.1:8000/mcp`. |
| Sensor is unsupported | Call `list_supported_sensors` and use an exact returned sensor name. |

## Development checks

```powershell
python -m pip install -r requirements-dev.txt
pytest
mypy obd_mcp
ruff check .
```
