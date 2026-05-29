# EMS Mode Integration Plan

## Background

The GoodWe ET inverter supports two orthogonal control axes:

| Axis | Register | Current support |
|---|---|---|
| `work_mode` (47000) | General / Off-grid / Backup / ECO | ✅ Implemented |
| `ems_mode` (47511) + `ems_power_limit` (47512) | Fine-grained battery/grid power control | ❌ Not implemented |

EMS mode is meaningful when `work_mode = 3` (ECO) or `work_mode = 0` (General).  
The goodwe library already exposes `ET.get_ems_mode()` / `ET.set_ems_mode(ems_mode, ems_power_limit)` — this integration is purely a GoodWe2MQTT layer task.

### Supported EMS modes (from `goodwe.inverter.EMSMode`)

| Value | Name | Behaviour | `ems_power_limit` |
|---|---|---|---|
| 1 | `AUTO` | Self-use; battery follows meter | Not used |
| 2 | `CHARGE_PV` | Charge from PV (priority) or Grid | Max charge W |
| 3 | `DISCHARGE_PV` | Discharge battery + PV surplus to grid | Max discharge W |
| 4 | `IMPORT_AC` | Charge from Grid (priority) or PV | Target charge W |
| 5 | `EXPORT_AC` | Sell to grid; PV preferred, battery tops up | Target export W |
| 6 | `CONSERVE` | Charge from PV only; no on-grid discharge | Not used |
| 7 | `OFF_GRID` | Forced off-grid operation | Not used |
| 8 | `BATTERY_STANDBY` | Battery idle (`P_battery = 0`) | Not used |
| 9 | `BUY_POWER` | Hold import at exactly `ems_power_limit` W | Target import W |
| 10 | `SELL_POWER` | Hold export at exactly `ems_power_limit` W | Target export W |
| 11 | `CHARGE_BATTERY` | Force charge at `ems_power_limit` W | Target charge W |
| 12 | `DISCHARGE_BATTERY` | Force discharge at `ems_power_limit` W | Target discharge W |

---

## Scope

Add the following to `src/goodwe2mqtt.py`:

1. **`get_ems_mode` helper** — reads EMS mode + power limit from inverter and publishes to MQTT state topic.
2. **`set_ems_mode` helper** — validates, calls library, reads back, publishes state.
3. **Two new `/control` commands** — `get_ems_mode` and `set_ems_mode`.
4. **Two new `/set/` topics** — `ems_mode` and `ems_power_limit_watts` (for raw direct writes and HA integration).
5. **New MQTT state topic** — `goodwe2mqtt/<serial>/ems_mode`.
6. **Home Assistant discovery entities** — `select` for EMS mode name, `number` for power limit.
7. **Tests** — unit tests for new control commands and set-topic handler paths.
8. **Docs** — update `docs/mqtt_api.md`.

---

## Implementation Steps

### Step 1 — `get_ems_mode` / `set_ems_mode` helpers in `Goodwe_MQTT`

Add alongside the existing `get_operation_mode` / `get_grid_export_limit` helpers:

```python
from goodwe.inverter import EMSMode

EMS_MODE_TOPIC_POSTFIX = "ems_mode"

async def get_ems_mode(self) -> None:
    """Reads EMS mode and power limit from the inverter and publishes to MQTT."""
    try:
        ems_mode = await self.inverter.get_ems_mode()
        power_limit = await self.inverter.read_setting("ems_power_limit")
        payload = {
            "ems_mode": ems_mode.value if ems_mode else None,
            "ems_mode_name": ems_mode.name if ems_mode else None,
            "ems_power_limit_watts": power_limit,
            "serial_number": self.serial_number,
            "last_seen": datetime.now(tzlocal.get_localzone()).isoformat(),
        }
        await self.send_mqtt_response(self.ems_mode_topic, payload)
        log.info(f'get_ems_mode {self.serial_number}: mode={ems_mode} limit={power_limit}W')
    except Exception as e:
        log.error(f'get_ems_mode {self.serial_number} failed: {e}')

async def set_ems_mode(self, ems_mode: EMSMode, power_limit_watts: Optional[int] = None) -> None:
    """Writes EMS mode (and optional power limit) to the inverter, then reads back."""
    try:
        await self.inverter.set_ems_mode(ems_mode, power_limit_watts)
        log.info(f'set_ems_mode {self.serial_number}: mode={ems_mode} limit={power_limit_watts}W')
        await self.get_ems_mode()
    except Exception as e:
        log.error(f'set_ems_mode {self.serial_number} failed: {e}')
```

Add `self.ems_mode_topic = f'{mqtt_topic}/{EMS_MODE_TOPIC_POSTFIX}'` to `__init__`.

---

### Step 2 — New `/control` command handlers

Add two new `elif` branches in `mqtt_client_task`, after the existing `set_general_operation_mode` block:

```python
elif 'get_ems_mode' in message_payload:
    log.info(f'mqtt_client_task {self.serial_number} Getting EMS mode')
    await self.get_ems_mode()

elif 'set_ems_mode' in message_payload:
    try:
        data = json.loads(message_payload)
        mode_value = int(data['set_ems_mode'])
        ems_mode = EMSMode(mode_value)
        power_limit = int(data['ems_power_limit_watts']) if 'ems_power_limit_watts' in data else None
        log.info(f'mqtt_client_task {self.serial_number} Setting EMS mode: {ems_mode} limit={power_limit}')
        await self.set_ems_mode(ems_mode, power_limit)
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.error(f'mqtt_client_task {self.serial_number} Invalid EMS payload: {e}')
```

---

### Step 3 — New `/set/` topic aliases

Extend `_INVERTER_SETTING_ALIAS` so the raw registers are writable via the existing `handle_set_message` path:

```python
_INVERTER_SETTING_ALIAS: Dict[str, str] = {
    "grid_export_limit_watts":     "grid_export_limit",
    "battery_charge_current_amps": "battery_charge_current",
    "ems_mode":                    "ems_mode",          # write integer value directly
    "ems_power_limit_watts":       "ems_power_limit",
}
```

This immediately enables:
```bash
mosquitto_pub ... -t goodwe2mqtt/SERIAL/set/ems_mode -m "8"             # BATTERY_STANDBY
mosquitto_pub ... -t goodwe2mqtt/SERIAL/set/ems_power_limit_watts -m "3000"
```

---

### Step 4 — Home Assistant Discovery

Add two new entities in `publish_ha_discovery`:

```python
# ems_mode – select
{
    "component": "select",
    "unique_id": f"{sn}_ems_mode",
    "name": "EMS Mode",
    "command_topic": f"{base}/set/ems_mode",
    "state_topic":   f"{base}/ems_mode",
    "value_template": "{{ value_json.ems_mode_name }}",
    "options": [m.name for m in EMSMode],
    "device": device,
},
# ems_power_limit – number
{
    "component": "number",
    "unique_id": f"{sn}_ems_power_limit_watts",
    "name": "EMS Power Limit",
    "command_topic": f"{base}/set/ems_power_limit_watts",
    "state_topic":   f"{base}/ems_mode",
    "value_template": "{{ value_json.ems_power_limit_watts }}",
    "unit_of_measurement": "W",
    "min": 0,
    "max": 15000,
    "step": 100,
    "device": device,
},
```

Note: HA select sends a string name (e.g. `"BATTERY_STANDBY"`), so `handle_set_message` needs a `ems_mode` branch that resolves the name to the integer value (similar to `work_mode`):

```python
EMS_MODE_OPTIONS: Dict[str, int] = {m.name: m.value for m in EMSMode}
```

And a corresponding branch in `handle_set_message`:
```python
elif setting_id == 'ems_mode':
    if payload_str in self.EMS_MODE_OPTIONS:
        value = self.EMS_MODE_OPTIONS[payload_str]
    else:
        value = int(payload_str)   # allow raw integer too
```

---

### Step 5 — MQTT state topic

New read-only topic published by `get_ems_mode`:

```
goodwe2mqtt/<serial>/ems_mode
```

Payload:
```json
{
  "ems_mode": 8,
  "ems_mode_name": "BATTERY_STANDBY",
  "ems_power_limit_watts": 0,
  "serial_number": "9010KETU21CW3302",
  "last_seen": "2026-05-29T12:00:00+02:00"
}
```

---

### Step 6 — Tests

Add to `tests/test_mqtt.py` or a new `tests/test_ems_mode.py`:

| Test | What it verifies |
|---|---|
| `test_control_get_ems_mode` | `get_ems_mode` payload contains `'get_ems_mode'` → `inverter.get_ems_mode()` called |
| `test_control_set_ems_mode_valid` | Valid `{"set_ems_mode": 8}` → `inverter.set_ems_mode(EMSMode.BATTERY_STANDBY, None)` |
| `test_control_set_ems_mode_with_limit` | `{"set_ems_mode": 5, "ems_power_limit_watts": 3000}` → correct call |
| `test_control_set_ems_mode_invalid` | Out-of-range integer → error logged, no inverter call |
| `test_set_topic_ems_mode_by_name` | `/set/ems_mode` payload `"BATTERY_STANDBY"` → writes `8` |
| `test_set_topic_ems_mode_by_int` | `/set/ems_mode` payload `"8"` → writes `8` |
| `test_set_topic_ems_power_limit` | `/set/ems_power_limit_watts` payload `"3000"` → writes `3000` |

---

### Step 7 — Documentation update

Update `docs/mqtt_api.md` — add to the **Actions** table:

```markdown
- **Get EMS Mode:**
  `{"get_ems_mode": 1}`
- **Set EMS Mode:**
  `{"set_ems_mode": 8}` (integer value, see EMSMode enum)
  `{"set_ems_mode": 5, "ems_power_limit_watts": 3000}` (with power setpoint)
```

Add to the `/set/` topics table:

| `setting_id` | Description | Payload type | Valid values |
|---|---|---|---|
| `ems_mode` | EMS mode | string (name) or integer | `"BATTERY_STANDBY"`, `8`, etc. |
| `ems_power_limit_watts` | EMS power setpoint | integer | 0 – 15000 (W) |

Add new **Read Topic**:

```markdown
### 6. EMS Mode
- **Topic:** `goodwe2mqtt/<serial>/ems_mode`
- **Payload:** JSON with `ems_mode`, `ems_mode_name`, `ems_power_limit_watts`, `serial_number`, `last_seen`
```

---

## MQTT API Summary (new commands)

```bash
# Get current EMS mode
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"get_ems_mode": 1}'

# Battery standby (block charging AND discharging)
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 8}'

# Force discharge at 3000 W
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 12, "ems_power_limit_watts": 3000}'

# Force charge at 2000 W
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 11, "ems_power_limit_watts": 2000}'

# Sell 5000 W to grid
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/control -m '{"set_ems_mode": 10, "ems_power_limit_watts": 5000}'

# Set via /set/ topic directly (raw integer)
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/set/ems_mode -m "8"
mosquitto_pub -h BROKER -t goodwe2mqtt/SERIAL/set/ems_mode -m "BATTERY_STANDBY"
```

---

## Open Questions

- **EMS mode availability:** Verify that `ems_mode` register (47511) is supported on all ET firmware versions in use. The goodwe library does not gate it behind a firmware version check (unlike EcoModeV2). If a register-not-found error is returned, the helper should log a warning and skip publishing.
- **Interaction with work_mode:** Document clearly that EMS mode is only meaningful when `work_mode` is General (0) or ECO (3). Setting EMS mode in Backup or Off-grid mode has undefined behaviour.
- **Power limit units:** The goodwe library docs say W; confirm inverter does not expect W/10 on some firmware.
- **HA select integration:** HA sends the string name from the `options` list; the `handle_set_message` resolver must convert `"BATTERY_STANDBY"` → `8` before writing the register.
