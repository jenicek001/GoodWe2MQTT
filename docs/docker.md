# Docker Deployment Guide

This guide explains how to run `goodwe2mqtt` using Docker and Docker Compose.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed.
- [Docker Compose](https://docs.docker.com/compose/install/) installed.

## Using Docker Compose (Recommended)

Docker Compose is the easiest way to manage the `goodwe2mqtt` service and an optional MQTT broker.

### 1. Setup Configuration

Create a `goodwe2mqtt.yaml` file (you can use the one in the root as a template) and configure your inverter(s).

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and adjust the values as needed:

```bash
cp .env.example .env
```

The application supports overriding any YAML configuration value using environment variables with the `G2M_` prefix.

### 3. Start the Stack

```bash
docker-compose up -d
```

This will start:
- `goodwe2mqtt`: The main daemon.
- `mqtt-broker`: An Eclipse Mosquitto instance (optional, see `docker-compose.yml`).

### 4. Check Logs

```bash
docker-compose logs -f
```

## Using Docker Run

If you prefer to run the container directly:

```bash
docker build -t goodwe2mqtt .

docker run -d \
  --name goodwe2mqtt \
  --network host \
  -v $(pwd)/goodwe2mqtt.yaml:/app/goodwe2mqtt.yaml:ro \
  -v $(pwd)/logs:/app/logs \
  -e G2M_LOG_LEVEL="INFO" \
  goodwe2mqtt
```

## Environment Variables

All configuration settings in `goodwe2mqtt.yaml` can be overridden using environment variables. The pattern is `G2M_<SECTION>_<KEY>`.

### Common Variables

| Variable | YAML Path | Description |
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

```
