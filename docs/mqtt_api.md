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
  {"grid_export_limit": 5000, "serial_number": "...", "last_seen": "..."}
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

### 1. Control Commands
- **Topic:** `goodwe2mqtt/<serial>/control`
- **Payload:** JSON object specifying the action.

#### Actions:

- **Get Grid Export Limit:**
  `{"get_grid_export_limit": 1}`
- **Set Grid Export Limit:**
  `{"set_grid_export_limit": 3000}` (Value in Watts)
- **Get Operation Mode:**
  `{"get_operation_mode": 1}`
- **Set General Operation Mode:**
  `{"set_general_operation_mode": 1}`
- **Set Eco Discharge (Battery to Grid):**
  `{"set_eco_discharge": 50}` (Value in % power)
- **Set Eco Charge (Grid to Battery):**
  `{"set_eco_charge": 50, "target_battery_soc": 80}` (Power % and Target SoC %)
