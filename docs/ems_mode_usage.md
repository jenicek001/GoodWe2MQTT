# EMS Mode — Usage Guide

This guide explains how to use GoodWe2MQTT's **EMS mode** control to fine-tune
battery charge/discharge and grid import/export behaviour on GoodWe ET
inverters.

> ⚠️ **Prerequisite: `work_mode` must be `General mode` (0) or `Eco mode` (4)**
>
> EMS mode is only honoured by the inverter when the general **work mode**
> (register `47000`) is set to `General mode` (0) or `Eco mode` (4).
> If the inverter is in `Off grid mode` (1) or `Backup mode` (2), EMS mode
> settings are ignored and behaviour is undefined — **always set `work_mode`
> first**, then set `ems_mode`.
>
> ```bash
> # 1. Put the inverter into Eco mode first
> mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/set/work_mode -m "Eco mode"
>
> # 2. Only then apply an EMS mode
> mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 8}'
> ```

---

## What EMS Mode Controls

`work_mode` selects the inverter's *general operating strategy* (grid-tied,
off-grid, backup, eco). **EMS mode** is a second, finer-grained control axis
that only applies within General/Eco work mode — it decides exactly how the
battery and grid interact from second to second (e.g. "hold export at exactly
3000 W", "force-charge the battery at 2000 W", "idle the battery entirely").

---

## Supported EMS Modes

| Value | Name | Behaviour | `ems_power_limit_watts` |
|---|---|---|---|
| 1 | `AUTO` | Self-use; battery follows the meter automatically | Not used |
| 2 | `CHARGE_PV` | Charge from PV (priority) or Grid | Max charge power |
| 3 | `DISCHARGE_PV` | Discharge battery + PV surplus to grid | Max discharge power |
| 4 | `IMPORT_AC` | Charge from Grid (priority) or PV | Target charge power |
| 5 | `EXPORT_AC` | Sell to grid; PV preferred, battery tops up | Target export power |
| 6 | `CONSERVE` | Charge from PV only; no on-grid discharge | Not used |
| 7 | `OFF_GRID` | Forced off-grid operation | Not used |
| 8 | `BATTERY_STANDBY` | Battery idle (`P_battery = 0`) | Not used |
| 9 | `BUY_POWER` | Hold import at exactly the limit | Target import power |
| 10 | `SELL_POWER` | Hold export at exactly the limit | Target export power |
| 11 | `CHARGE_BATTERY` | Force-charge the battery at the limit | Target charge power |
| 12 | `DISCHARGE_BATTERY` | Force-discharge the battery at the limit | Target discharge power |

`ems_power_limit_watts` accepts **0 – 15000 W** and is only meaningful for the
modes listed above (ignored otherwise).

---

## How to Set EMS Mode

There are two equivalent ways to control EMS mode over MQTT.

### Option A — `/control` topic (JSON command)

> The `/control` payload must be a valid JSON **object** (`{...}`). Malformed
> JSON, or valid JSON that isn't an object (e.g. a bare number or array), is
> rejected and logged as an error without affecting the inverter. The value
> attached to `get_ems_mode` is ignored — only the key's presence matters.

```bash
# Read current EMS mode + power limit
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"get_ems_mode": 1}'

# Set EMS mode only (modes without a power limit, e.g. AUTO, BATTERY_STANDBY, CONSERVE)
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 8}'

# Set EMS mode with a power setpoint
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 12, "ems_power_limit_watts": 3000}'
```

### Option B — `/set/` topics (raw register write, Home Assistant friendly)

```bash
# By name
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/set/ems_mode -m "BATTERY_STANDBY"

# By raw integer
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/set/ems_mode -m "8"

# Power limit
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/set/ems_power_limit_watts -m "3000"
```

Both options publish the confirmed state to:

```
goodwe2mqtt/SERIAL/ems_mode
```

```json
{
  "ems_mode": 8,
  "ems_mode_name": "BATTERY_STANDBY",
  "ems_power_limit_watts": 0,
  "serial_number": "SERIAL",
  "last_seen": "2026-07-21T12:00:00+02:00"
}
```

Subscribe to see the confirmed state after every change:

```bash
mosquitto_sub -h BROKER -t goodwe2mqtt/SERIAL/ems_mode
```

---

## Common Scenarios

| Goal | Command |
|---|---|
| Let the inverter manage the battery normally | `{"set_ems_mode": 1}` (`AUTO`) |
| Block all battery charge/discharge (e.g. maintenance) | `{"set_ems_mode": 8}` (`BATTERY_STANDBY`) |
| Force-charge the battery at 2000 W | `{"set_ems_mode": 11, "ems_power_limit_watts": 2000}` |
| Force-discharge the battery at 3000 W | `{"set_ems_mode": 12, "ems_power_limit_watts": 3000}` |
| Sell exactly 5000 W to the grid | `{"set_ems_mode": 10, "ems_power_limit_watts": 5000}` |
| Hold grid import at exactly 1000 W | `{"set_ems_mode": 9, "ems_power_limit_watts": 1000}` |
| Charge from PV only, never discharge to grid | `{"set_ems_mode": 6}` (`CONSERVE`) |

---

## Home Assistant

On startup GoodWe2MQTT publishes MQTT Discovery entities:

| Entity | Component | Notes |
|---|---|---|
| EMS Mode | `select` | Options are the `EMSMode` names listed above |
| EMS Power Limit | `number` | 0 – 15000 W |

Both entities share the same `goodwe2mqtt/<serial>/ems_mode` state topic, so
they always reflect the latest confirmed mode/limit together.

> Remember: the **Operation Mode** `select` entity (`work_mode`) must be set
> to `General mode` or `Eco mode` before the EMS Mode entity has any effect.

---

## Troubleshooting

- **EMS mode changes have no effect** — check `work_mode` first
  (`goodwe2mqtt/SERIAL/operation_mode`); it must be `General mode` (0) or
  `Eco mode` (4).
- **`ems_mode` in the published state is `null`** — the inverter returned an
  unrecognised value for the `ems_mode` register; this can happen on older
  firmware that does not support EMS mode. Check the daemon logs for details.
- **Out-of-range power limit rejected** — `ems_power_limit_watts` must be
  between 0 and 15000 W; values outside this range are rejected and logged
  as an error without being sent to the inverter.
- **Invalid `/control` payload rejected** — the payload must be a JSON
  object; malformed JSON or a non-object JSON value (bare number, string,
  array) is logged as an error and ignored.
- **`ems_mode` shows a value I never set** — GoodWe2MQTT never writes
  `ems_mode` on its own (only the `set_ems_mode` command does, on explicit
  request). `ems_mode` and `ems_power_limit` are *persistent* inverter
  settings (register `47511`/`47512`), so the very first read after
  deploying this feature simply reports whatever was already stored on the
  inverter — e.g. from the SEMS app, a previous manual Modbus write, or
  factory defaults. This is normal; if you want self-managed behaviour,
  explicitly set `AUTO`:
  ```bash
  mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 1}'
  ```
  A mode like `CHARGE_BATTERY` with `ems_power_limit_watts: 0` and a full
  battery has no visible effect (there is no power to charge with), so it
  can sit unnoticed for a long time before being reported here.

See also: [MQTT API Specification](mqtt_api.md) and the original
[EMS Mode Integration Plan](ems_mode_integration_plan.md).
