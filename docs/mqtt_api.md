# MQTT API Specification

GoodWe2MQTT uses a hierarchical topic structure based on the inverter serial number.

**Base Topic Pattern:** `<topic_prefix>/<serial_number>/`

By default, `<topic_prefix>` is `goodwe2mqtt`.

## Read Topics (Daemon -> Broker)

### 1. Runtime Data
- **Topic:** `goodwe2mqtt/<serial>/runtime_data`
- **Interval:** Configurable (`runtime_data_interval_seconds`)
- **Payload:** JSON object containing all available sensors from the inverter.
- **Example:**
  ```json
  {"timestamp": "2026-01-24T12:00:00", "vpv1": 450.5, "ppv": 3200, ...}
  ```

### 2. Fast Runtime Data
- **Topic:** `goodwe2mqtt/<serial>/fast_runtime_data`
- **Interval:** Configurable (`fast_runtime_data_interval_seconds`)
- **Payload:** Same format as Runtime Data, but published more frequently.

### 3. Grid Export Limit
- **Topic:** `goodwe2mqtt/<serial>/grid_export_limit`
- **Payload:** JSON object with current export limit.
  ```json
  {"grid_export_limit_watts": 5000, "serial_number": "...", "last_seen": "..."}
  ```

### 4. Operation Mode
- **Topic:** `goodwe2mqtt/<serial>/operation_mode`
- **Payload:** JSON object with current operation mode.
  ```json
  {"operation_mode": 1, "serial_number": "...", "last_seen": "..."}
  ```

### 5. Daemon Status (Heartbeat)
- **Topic:** `goodwe2mqtt/<serial>/status`
- **Payload:** `"online"` (JSON string)
- **Interval:** 30 seconds

---

## Control Topics (Broker -> Daemon)

### 1. Control Commands (Legacy JSON format)
- **Topic:** `goodwe2mqtt/<serial>/control`
- **Payload:** JSON object specifying the action.

#### Actions:

- **Get Grid Export Limit:**
  `{"get_grid_export_limit_watts": 1}`
- **Set Grid Export Limit:**
  `{"set_grid_export_limit_watts": 3000}` (Value in Watts)
- **Get Operation Mode:**
  `{"get_operation_mode": 1}`
- **Set General Operation Mode:**
  `{"set_general_operation_mode": 1}`
- **Set Eco Discharge (Battery to Grid):**
  `{"set_eco_discharge_percent": 50}` (Value in % of rated power, 0–100)
- **Set Eco Charge (Grid to Battery):**
  `{"set_eco_charge_percent": 50, "target_battery_soc_percent": 80}` (Power % and Target SoC %)

---

### 2. Direct Setting Write (`/set/` topics)

Each writable inverter setting has a dedicated topic.  The daemon writes the
value to the inverter (with automatic retry / exponential backoff), then reads
the setting back and publishes the confirmed value on the matching state topic.

**Command Topic:** `goodwe2mqtt/<serial>/set/<setting_id>`  
**State Topic:**   `goodwe2mqtt/<serial>/state/<setting_id>`

Supported settings:

| `setting_id` | Description | Payload type | Valid values |
|---|---|---|---|
| `work_mode` | Operation mode | string or integer | `"General mode"` (0), `"Off grid mode"` (1), `"Backup mode"` (2), `"Eco mode"` (4) |
| `battery_charge_current_amps` | Max battery charge current | integer | 0 – 25 (A) |
| `grid_export_limit_watts` | Grid export power limit | integer | 0 – 10000 (W) |

**Examples:**

```bash
# Set operation mode to Eco mode (enables grid charging)
mosquitto_pub -h localhost -t goodwe2mqtt/SERIAL/set/work_mode -m "Eco mode"

# Set grid export limit to 5000 W
mosquitto_pub -h localhost -t goodwe2mqtt/SERIAL/set/grid_export_limit_watts -m "5000"

# Set battery charge current to 10 A
mosquitto_pub -h localhost -t goodwe2mqtt/SERIAL/set/battery_charge_current_amps -m "10"
```

The state topic payload is a JSON object:
```json
{"work_mode": 4}
{"grid_export_limit_watts": 5000}
{"battery_charge_current_amps": 10}
```

---

### 3. Home Assistant MQTT Discovery

On startup the daemon publishes HA MQTT Discovery payloads so that the
entities appear automatically in Home Assistant.

| Entity | HA Component | Discovery topic |
|---|---|---|
| Operation Mode | `select` | `homeassistant/select/<serial>_work_mode/config` |
| Battery Charge Current | `number` | `homeassistant/number/<serial>_battery_charge_current_amps/config` |
| Grid Export Limit | `number` | `homeassistant/number/<serial>_grid_export_limit_watts/config` |

---

## SEC1000S Energy Controller

The SEC1000S uses `goodwe2mqtt/sec1000s/<serial_number>/` as its base topic,
where `<serial_number>` is set via `G2M_SEC1000S_<N>_SERIAL_NUMBER`.

### Read Topics

| Topic | Interval | Payload |
|---|---|---|
| `goodwe2mqtt/sec1000s/<serial_number>/grid_export_limit` | `grid_export_limit_interval_seconds` | `{"control_mode": 3, "total_capacity_watts": 14000, "grid_export_limit_watts": 2500, "serial_number": "...", "effective_ceiling_watts": 9000, "last_seen": "..."}` |
| `goodwe2mqtt/sec1000s/<serial_number>/telemetry` | `telemetry_interval_seconds` | `{"v1": 240.0, ..., "meters_power_watts": 3084, "serial_number": "...", "last_seen": "..."}` |
| `goodwe2mqtt/sec1000s/<serial_number>/status` | 30 s | `"online"` |

### Control Topic

**Topic:** `goodwe2mqtt/sec1000s/<serial_number>/control`

| Command | Payload |
|---|---|
| Set grid export limit | `{"set_grid_export_limit_watts": 1000}` |
| Get grid export limit | `{"get_grid_export_limit_watts": 1}` |

**Examples:**

```bash
# Set grid export limit to 1000 W
mosquitto_pub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/sec1000s/99000SEC235L0256/control \
  -m '{"set_grid_export_limit_watts":1000}'

# Ask the SEC1000S to report the current limit (reply arrives on the grid_export_limit topic)
mosquitto_pub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/sec1000s/99000SEC235L0256/control \
  -m '{"get_grid_export_limit_watts":1}'

# Listen to the SEC1000S grid export limit topic (verify the limit was accepted)
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/sec1000s/99000SEC235L0256/grid_export_limit

# Listen to SEC1000S telemetry (voltage, current, power per phase)
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/sec1000s/99000SEC235L0256/telemetry

# Listen to all SEC1000S topics at once
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t 'goodwe2mqtt/sec1000s/99000SEC235L0256/#'
```

---

## Useful mosquitto_sub Examples (GoodWe ET Inverters)

Replace `SERIAL` with the inverter serial number (matches `G2M_GOODWE_INVERTERS_<N>_SERIAL_NUMBER`).

```bash
# Listen to fast runtime data (updated every second by default)
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/SERIAL/fast_runtime_data

# Listen to regular runtime data
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/SERIAL/runtime_data

# Listen to grid export limit changes on the inverter
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/SERIAL/grid_export_limit

# Ask the inverter to report its current grid export limit
mosquitto_pub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/SERIAL/control \
  -m '{"get_grid_export_limit_watts":1}'

# Set the inverter grid export limit to 5000 W via /set/ topic
mosquitto_pub -h localhost -u mqtt_username -P mqtt_password \
  -t goodwe2mqtt/SERIAL/set/grid_export_limit_watts \
  -m '5000'

# Listen to all topics for one inverter
mosquitto_sub -h localhost -u mqtt_username -P mqtt_password \
  -t 'goodwe2mqtt/SERIAL/#'
```
