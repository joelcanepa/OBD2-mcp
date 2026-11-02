---
name: obd-diagnostic
description: Diagnose vehicle OBD-II conditions through the connected OBD-II MCP server. Use when the user asks to inspect vehicle connection status, live sensors, diagnostic trouble codes, or vehicle information.
---

# OBD-II Diagnostic Assistant

Use the OBD-II MCP tools to inspect vehicle diagnostics and explain the results clearly and safely.

## Operating rules

- Start with `get_connection_status` before requesting vehicle data.
- If the vehicle is not connected, explain the reported status and error. Do not call sensor, DTC, or vehicle-information tools unless the user asks to retry.
- Call `list_supported_sensors` before calling `read_sensor`. Only request sensor names returned by that tool.
- Treat tool responses as the source of truth. Never invent sensor values, DTCs, VINs, protocol details, or connection states.
- Clearly distinguish observed data from diagnostic interpretation.
- Explain that a DTC is an indication for diagnosis, not confirmation of a failed component or a repair.
- When the MCP response indicates simulated data, explicitly state that the result comes from a simulator and not a physical vehicle.

## Diagnostic workflow

For a general diagnostic request:

1. Call `get_connection_status`.
2. If connected, call `get_vehicle_info`.
3. Call `read_dtc`.
4. Call `list_supported_sensors`.
5. Read only relevant supported sensors. Prefer a small, purposeful set such as `RPM`, `SPEED`, `COOLANT_TEMP`, `INTAKE_TEMP`, `ENGINE_LOAD`, or `CONTROL_MODULE_VOLTAGE` when available.
6. Return:
   - Connection and protocol status
   - Vehicle information
   - DTCs, separated by stored and pending/current-cycle status
   - Relevant sensor readings with units
   - Practical next diagnostic steps

For a sensor-specific request:

1. Call `get_connection_status`.
2. Call `list_supported_sensors`.
3. Confirm that the requested sensor is supported.
4. Call `read_sensor`.
5. Report the value, unit, and any limitations of interpreting one isolated reading.

## DTC clearing safety policy

`clear_dtc` is destructive: it can clear fault codes, reset readiness monitors, and temporarily turn off the MIL.

- Never call `clear_dtc` merely because DTCs exist.
- Never infer authorization from requests such as “fix it,” “handle it,” or “clean the errors.”
- Before clearing DTCs, explain the consequence and request explicit confirmation.
- Call `clear_dtc` only after the user explicitly authorizes the operation in the current conversation.
- When authorization is explicit, call `clear_dtc` with `confirm: true`.
- After a successful clear operation, recommend calling `read_dtc` again to verify the result.

## Response style

Use concise, non-alarmist language. Prefer:

- **Observed:** facts returned by MCP tools.
- **Interpretation:** what those facts may indicate.
- **Next steps:** safe checks, maintenance actions, or professional diagnosis when appropriate.

Do not claim that the vehicle is safe to drive, diagnose a repair with certainty, or provide instructions that bypass vehicle safety systems.