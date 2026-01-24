# Technology Stack

## Core Technologies
- **Python 3:** The primary programming language used for the daemon logic.
- **goodwe Library:** Used for direct communication and data retrieval from GoodWe inverters.
- **aiomqtt & paho-mqtt:** Asynchronous and standard MQTT clients for reporting data and receiving commands.

## Supporting Libraries
- **PyYAML:** For parsing the project's configuration file (`goodwe2mqtt.yaml`).
- **python-dateutil, pytz, & tzlocal:** For robust handling of timezones and date calculations.

## Development & Quality Tools
- **Pytest:** Core testing framework.
- **Ruff:** Fast Python linter and formatter.
- **Mypy:** Static type checker for Python.
- **GitHub Actions:** CI/CD pipeline for automated testing and quality gates.
- **Mermaid.js:** Used for architectural and flow diagrams in documentation.
