# GoodWe2MQTT AI Instructions

Knowledge and patterns for working on the GoodWe2MQTT project.

## Architecture & Frameworks
- **Core**: Python 3 application using `asyncio` for non-blocking I/O.
- **Inverter Communication**: Uses the `goodwe` library (UDP protocol). Interfaces with GoodWe ET/ES families.
- **MQTT**: Uses `aiomqtt` for asynchronous MQTT interactions (v2.x API).
- **Service Pattern**: Cada inverter defined in `goodwe2mqtt.yaml` is managed by an instance of `Goodwe_MQTT` class.

## Critical Files
- [src/goodwe2mqtt.py](src/goodwe2mqtt.py): Main application implementation with `Goodwe_MQTT`, `main_loop`, and `mqtt_client_task`.
- [goodwe2mqtt.py](goodwe2mqtt.py): Compatibility entrypoint that loads and runs the implementation from `src/`.
- [goodwe2mqtt.yaml](goodwe2mqtt.yaml): Central configuration for MQTT brokers, inverter IPs/Serials, and logging.
- [src/logger.py](src/logger.py): Shared logging configuration. Always use `from logger import log`.

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
- **Deployment**: Docker-first deployment. Use [docs/docker.md](docs/docker.md) and `docker compose up -d`.

## Integration Points
- **MQTT Topics**:
    - `.../runtime_data`: Full inverter data dumps.
    - `.../control`: Incoming JSON commands.
    - `.../grid_export_limit`: Current limit status.
- **Data Persistence**: Local JSON dumps in `data/` directory (created via `dump_to_json`).
