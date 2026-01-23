# GoodWe2MQTT AI Instructions

Knowledge and patterns for working on the GoodWe2MQTT project.

## Architecture & Frameworks
- **Core**: Python 3 application using `asyncio` for non-blocking I/O.
- **Inverter Communication**: Uses the `goodwe` library (UDP protocol). Interfaces with GoodWe ET/ES families.
- **MQTT**: Uses `aiomqtt` for asynchronous MQTT interactions (v2.x API).
- **Service Pattern**: Cada inverter defined in `goodwe2mqtt.yaml` is managed by an instance of `Goodwe_MQTT` class.

## Critical Files
- [goodwe2mqtt.py](goodwe2mqtt.py): Main entry point, contains `Goodwe_MQTT` class with `main_loop` (polling) and `mqtt_client_task` (control).
- [goodwe2mqtt.yaml](goodwe2mqtt.yaml): Central configuration for MQTT brokers, inverter IPs/Serials, and logging.
- [logger.py](logger.py): Shared logging configuration. Always use `from logger import log`.
- [install.sh](install.sh): Scaffolding for deployment (user creation, venv, systemd service).

## Patterns & Conventions
- **Asynchronous Loop**: The `Goodwe_MQTT.main_loop` handles periodic polling. Use `asyncio.sleep` instead of `time.sleep`.
- **MQTT Commands**: Inverters subscribe to `goodwe2mqtt/{serial}/control`. Commands are JSON strings (e.g., `{"set_grid_export_limit": 5000}`).
- **Error Handling**: Use `goodwe.exceptions.MaxRetriesException` and `goodwe.exceptions.RequestFailedException` when interacting with the inverter.
- **Time/Timezone**: Uses `tzlocal` and `pytz` for generating timezone-aware local times for payloads.
- **Logging**: Do not use `print()`. Use `log.info()`, `log.debug()`, or `log.error()`.

## Development Workflows
- **Configuration**: Always update [goodwe2mqtt.yaml](goodwe2mqtt.yaml) for new deployment settings.
- **Manual Control**: Test MQTT commands using `mosquitto_pub`:
  ```bash
  mosquitto_pub -h localhost -t goodwe2mqtt/SERIAL/control -m '{"set_grid_export_limit": 5000}'
  ```
- **Deployment**: Run [install.sh](install.sh) to set up the environment. The service is managed via `systemctl --user` or global systemd as defined in `goodwe2mqtt.service`.

## Integration Points
- **MQTT Topics**:
    - `.../runtime_data`: Full inverter data dumps.
    - `.../control`: Incoming JSON commands.
    - `.../grid_export_limit`: Current limit status.
- **Data Persistence**: Local JSON dumps in `data/` directory (created via `dump_to_json`).
