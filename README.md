# GoodWe2MQTT
Daemon to read runtime data and configure GoodWe Inverters reporting and control via MQTT.
It is based on GoodWe project https://github.com/marcelblijleven/goodwe

Supports the ET/EH/BT/BH hybrid families (what this daemon was built for) and the grid-only
DT/MS/D-NS/XS families. The family is detected from the inverter's serial number; set
`G2M_GOODWE_INVERTERS_<N>_FAMILY` only to override that. Commands and Home Assistant entities are
limited to what the connected inverter actually supports, so a grid-only DT inverter is offered its
export limit and nothing battery-related.

SEC1000S protocol reverse-engineering sourced from https://github.com/jozef-moravcik-homeassistant/GoodWe-SEC1000S

## Documentation
- [Docker Deployment Guide](docs/docker.md)
- [Architecture](docs/architecture.md)
- [Dependency Management](docs/dependency_management.md)
- [MQTT API Specification](docs/mqtt_api.md)
- [EMS Mode Usage Guide](docs/ems_mode_usage.md)
- [Contributing Guidelines](CONTRIBUTING.md)
