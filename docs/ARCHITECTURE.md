# Architecture and concepts

## 1. Purpose and scope

This project is a local bridge between an MCP client and a vehicle ECU. It turns
six high-level MCP tools into OBD-II exchanges performed through an ELM327 serial
adapter. A stateful simulator implements the same driver-shaped interface for
development without hardware.

The server intentionally does not diagnose the mechanical cause of a fault. It
acquires and normalizes evidence: connection state, supported PIDs, live sensor
values, DTCs, VIN, MIL state, and protocol information.

## 2. System map

```text
MCP client
    │  stdio or Streamable HTTP
    ▼
FastMCP tools                 obd_mcp/server.py
    │  async use cases
    ▼
OBDService                    obd_mcp/obd_service.py
    │  asyncio.to_thread
    ▼
ConnectionManager             obd_mcp/connection.py
    │  serialized query + retry
    ▼
python-OBD / SimulatedConnection
    │
    ▼
ELM327 → vehicle ECU          (hardware mode only)
```

Configuration (`obd_mcp/config.py`) is assembled before this chain starts. The
service and connection layers do not know whether MCP arrived over stdio or HTTP.

## 3. Responsibilities by module

| Module | Responsibility | Deliberately does not do |
| --- | --- | --- |
| `config.py` | Merge, coerce, and validate runtime settings | Open connections |
| `server.py` | Define MCP tools, lifecycle, transport, and destructive-action confirmation | Speak serial OBD-II directly |
| `obd_service.py` | Implement use cases and normalize driver values to JSON-safe records | Own threads or serial-port state |
| `connection.py` | Own one connection, lock access, discover commands, reconnect, retry | Interpret sensor or DTC meaning |
| `simulation.py` | Emulate the subset of the python-OBD interface used by the project | Emulate every ECU behavior |
| `scripts/mcp_terminal_tester.py` | Validate the complete MCP protocol path interactively | Bypass the MCP server |

## 4. Configuration precedence

Settings are overlaid in this order, from lowest to highest priority:

```text
dataclass defaults ← JSON file ← environment ← command-line overrides
```

Think of this as transparent sheets stacked on a light table. Each sheet only
covers values it defines; the topmost visible value wins. A CLI value of `None`
means “no ink on this sheet,” so it does not erase an environment or JSON value.

Validation occurs after the layers are merged. This ensures the effective value,
not each intermediate representation, is checked.

## 5. Connection lifecycle and reconnection

`ConnectionManager` is the sole owner of the driver connection. A request follows
this sequence:

1. Acquire the re-entrant lock.
2. Reuse a live connection or attempt a bounded connection cycle.
3. Run the complete operation while holding the lock.
4. If communication fails, discard the connection and reconnect.
5. Retry the operation exactly once; convert a second failure into
   `OBDCommunicationError`.

The connection attempts within a cycle use linear backoff:

```text
wait after attempt n = reconnect_delay × n
```

### Analogy: a single-lane service bay

The ELM327 is like one mechanic at a one-car service bay. Several MCP requests may
arrive together, but letting them speak over the same serial line simultaneously
would mix their questions and answers. The lock is the bay door: one complete job
enters, finishes, and leaves before the next begins.

Reconnection is like replacing a dropped phone call. The manager redials and
repeats the question once. It does not retry indefinitely, because an operation
such as clearing DTCs may have reached the ECU even when the reply was lost.

## 6. Async boundary

python-OBD performs blocking serial I/O, while FastMCP serves asynchronous tools.
`OBDService` bridges the two with `asyncio.to_thread`.

### Analogy: a reception desk and a workshop

The event loop is a receptionist who must remain available to every visitor. A
serial query is workshop labor that may take seconds. The receptionist hands that
job to a worker thread instead of disappearing into the workshop. The connection
lock still ensures that workers use the single adapter one at a time.

This separation preserves responsiveness; it does not make the adapter capable of
parallel OBD-II conversations.

## 7. PID discovery and sensor filtering

On connection, python-OBD discovers commands supported by the ECU. The manager
caches that set. The service exposes only commands that represent live sensors,
excluding protocol metadata, DTC operations, VIN, status, and PID-discovery
commands.

`read_sensors` validates the whole requested name list before querying. Sensor
names are trimmed and normalized to uppercase. A known python-OBD command is still
rejected if the current vehicle did not advertise it.

### Analogy: a restaurant menu

python-OBD's global command registry is a cookbook; it contains everything the
library knows how to prepare. The connected vehicle's discovered command set is
today's menu. A recipe may exist in the cookbook, but the client may order only
what this ECU placed on the menu.

## 8. Data normalization

Driver values cannot always be serialized directly as JSON. Quantities may carry
Pint units or NumPy scalar values. `_json_value` converts them to a stable shape:

```json
{"name": "RPM", "value": 825, "unit": "revolutions_per_minute"}
```

Primitive values retain their value and use a null unit. Tuples become lists;
unknown objects fall back to their string representation. A null response for one
sensor becomes a per-sensor error instead of invalidating every reading in a batch.

## 9. Diagnostic trouble codes and safety

Reading DTCs is non-destructive. Stored and pending/current-cycle codes are queried
separately and tagged with their status before being combined.

Clearing DTCs is different: it can erase freeze-frame evidence, reset readiness
monitors, and turn off the MIL temporarily. The MCP tool therefore requires
`confirm=true`. The lower-level service assumes its caller has already obtained
approval; this keeps policy at the external boundary where user intent is known.

After clearing, the response says the command was sent—not that the underlying
fault was repaired. The correct verification is another DTC read after the ECU has
had an opportunity to run its monitors.

## 10. Simulation model

`SimulatedConnection` uses dependency injection: `ConnectionManager` receives it
as the connection factory instead of `obd.OBD`. No service or MCP tool needs a
simulation-specific branch.

The simulator is deterministic within a process:

- A sample counter advances on every query.
- Sensor values follow smooth sine waves around plausible baselines.
- Stored and pending DTC collections are mutable session state.
- Clearing DTCs changes later DTC, MIL, and DTC-count responses.
- Closing the connection changes its reported driver status.

### Analogy: a flight simulator cockpit

The controls and instruments have the same interface used by the real system, but
the world behind them is generated. Tests can practice the entire procedure—read
sensors, inspect warnings, clear codes, verify state—without claiming that the
generated values represent a real engine.

## 11. Error model

| Exception | Meaning | Typical source |
| --- | --- | --- |
| `ConfigurationError` | Effective configuration is invalid | JSON, environment, CLI, range checks |
| `OBDConnectionError` | No live adapter/ECU connection can be established | Bluetooth, serial port, ignition |
| `OBDCommunicationError` | An established exchange failed, including its retry | Dropped link, driver/query failure |
| `UnsupportedCommandError` | Command is unknown, non-sensor, or unsupported by this ECU | Client input or vehicle capability |
| `InvalidOBDResponseError` | A required response object is absent | Malformed/empty clear-DTC exchange |

Connection status is intentionally best-effort and returns diagnostic state rather
than raising when the adapter is unavailable.

## 12. Extension guide

To add a new read-only MCP capability:

1. Confirm python-OBD exposes the required command and response shape.
2. Add a synchronous service helper that performs one logical operation through
   `ConnectionManager.execute`.
3. Add an async service method that delegates with `asyncio.to_thread`.
4. Add a small MCP tool in `create_server` that validates external input.
5. Test with a fake connection, then add simulator behavior if the capability
   should work without hardware.
6. Document the response contract and whether the operation changes ECU state.

Keep confirmation for destructive operations at the MCP boundary, keep serial
ownership in `ConnectionManager`, and keep driver-to-JSON conversion in the
service layer.

## 13. Verification strategy

- `tests/test_config.py` checks precedence and coercion.
- `tests/test_service.py` checks discovery, normalization, DTCs, vehicle data,
  and clear semantics against a fake driver.
- `tests/test_simulation.py` checks the integrated service/simulator state flow.
- `scripts/mcp_terminal_tester.py` checks protocol negotiation and the public MCP
  tools through a real stdio subprocess.

Run the static and automated checks with:

```bash
pytest
mypy obd_mcp
ruff check .
```
