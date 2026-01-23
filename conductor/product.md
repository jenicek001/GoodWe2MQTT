# Product Definition

## Initial Concept
Daemon to read runtime data and configure GoodWe Inverters reporting and control via MQTT.

## Target Users
- **Home automation enthusiasts:** Users of platforms like Home Assistant or OpenHAB who want to integrate their solar data.
- **Solar power plant owners:** Individuals looking for a way to monitor their GoodWe inverters independently.
- **Developers:** Those building custom energy management systems requiring direct access to inverter data.

## Goals
- **Real-time monitoring:** Provide a continuous stream of runtime data from GoodWe inverters via the MQTT protocol.
- **Remote configuration:** Enable the ability to change inverter operating modes and settings remotely through MQTT messages.

## Key Features
- **Asynchronous Data Collection:** A robust asyncio-based loop that polls data from the inverter without blocking.
- **Configurable MQTT Publishing:** Flexible integration with any MQTT broker, allowing users to define topics and connection settings.
