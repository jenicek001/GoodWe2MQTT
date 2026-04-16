# Docker Deployment Guide

This guide explains how to run `goodwe2mqtt` using Docker and Docker Compose.

## Deployment Model

- Docker is the supported deployment path.
- One container can manage multiple inverters when they are listed in `.env` using indexed `G2M_GOODWE_INVERTERS_<index>_*` variables.
- Run separate containers only when you intentionally need strict isolation between inverter groups (separate brokers, credentials, networks, or restart policy boundaries).

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed.
- [Docker Compose](https://docs.docker.com/compose/install/) installed.

## Using Docker Compose (Recommended)

Docker Compose is the easiest way to manage the `goodwe2mqtt` service and an optional MQTT broker.

### 1. Configure Environment Variables

Copy `.env.example` to `.env` and adjust the values as needed:

```bash
cp .env.example .env
```

Set at least one inverter:

```bash
G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER=INV1_SERIAL
G2M_GOODWE_INVERTERS_0_IP_ADDRESS=192.168.1.100
```

Add more inverters by increasing the index (`_1_`, `_2_`, ...).

### 2. Start the Stack

```bash
docker compose up -d
```

This will start:
- `goodwe2mqtt`: The main daemon.
- `mqtt-broker`: An Eclipse Mosquitto instance (optional, see `docker-compose.yml`).

### 3. Check Logs

```bash
docker compose logs -f
```

## Using Docker Run

If you prefer to run the container directly:

```bash
docker build -t goodwe2mqtt .

docker run -d \
  --name goodwe2mqtt \
  --network host \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  goodwe2mqtt
```

## Environment Variables

Configuration is provided via environment variables using the `G2M_<SECTION>_<KEY>` pattern.

### Common Variables

| Variable | Config Path | Description |
|----------|-----------|-------------|
| `G2M_LOG_LEVEL` | `logger.log_level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `G2M_MQTT_BROKER_IP` | `mqtt.broker_ip` | MQTT Broker IP Address |
| `G2M_MQTT_BROKER_PORT` | `mqtt.broker_port` | MQTT Broker Port |
| `G2M_MQTT_USERNAME` | `mqtt.username` | MQTT Username |
| `G2M_MQTT_PASSWORD` | `mqtt.password` | MQTT Password |

### Inverter Overrides

For lists like inverters, use the index:
- `G2M_GOODWE_INVERTERS_0_IP_ADDRESS`
- `G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER`

## Security

The container runs as a non-root user (`goodwe`) for improved security.
