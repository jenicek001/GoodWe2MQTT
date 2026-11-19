# Docker Deployment Guide

This guide explains how to run `goodwe2mqtt` using Docker and Docker Compose.

## Deployment Model

- Docker is the supported deployment path.
- One container can manage multiple inverters when they are listed in `.env` using indexed `G2M_GOODWE_INVERTERS_<index>_*` variables.
- Run separate containers only when you intentionally need strict isolation between inverter groups (separate brokers, credentials, networks, or restart policy boundaries).
- **Most users already have an MQTT broker** (e.g. Home Assistant's Mosquitto add-on). In that case, just point `G2M_MQTT_BROKER_IP` at it and run the daemon only.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed.
- [Docker Compose](https://docs.docker.com/compose/install/) installed.

## Using Docker Compose (Recommended)

### 1. Configure Environment Variables

Copy `.env.example` to `.env` and adjust the values:

```bash
cp .env.example .env
```

Set at minimum your broker address and at least one inverter:

```bash
G2M_MQTT_BROKER_IP=192.168.1.10   # IP of your existing MQTT broker
G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER=INV1_SERIAL
G2M_GOODWE_INVERTERS_0_IP_ADDRESS=192.168.1.100
```

Add more inverters by increasing the index (`_1_`, `_2_`, ...).

The inverter family (ET, ES, DT, or the equivalent names) normally needs no configuration: it is
detected from the serial number. Set `G2M_GOODWE_INVERTERS_<index>_FAMILY` only to pin one:

```bash
G2M_GOODWE_INVERTERS_0_FAMILY=ET      # only if auto-detection picks the wrong family
```

### 2a. Start — daemon only (recommended for existing setups)

Use this when you already have an MQTT broker (Home Assistant, standalone Mosquitto, etc.):

```bash
docker compose up -d
```

This starts only the `goodwe2mqtt` daemon.

### 2b. Start — with bundled Mosquitto broker

Use this when you have no existing MQTT broker and want one included.
Set `G2M_MQTT_BROKER_IP=localhost` in `.env` (both services share host networking), then:

```bash
docker compose -f docker-compose.yml -f docker-compose.mqtt.yml up -d
```

This starts both `goodwe2mqtt` and an Eclipse Mosquitto instance using the config in `mosquitto/config/mosquitto.conf`.

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

## Upgrading to a New Version

`goodwe2mqtt` has no separate release/image tags — the image is always built
locally from the checked-out source (`build: .` in `docker-compose.yml`).
Deploying a new version means: pull the new code, rebuild the image, and
recreate the container.

### Using Docker Compose (Recommended)

```bash
# 1. Pull the latest code (or checkout the desired tag/branch)
git pull

# 2. Check .env.example for any new/changed variables and update your .env accordingly
diff .env.example .env

# 3. Rebuild the image and recreate the container(s)
docker compose up -d --build
# ...or, if using the bundled Mosquitto broker:
docker compose -f docker-compose.yml -f docker-compose.mqtt.yml up -d --build

# 4. Verify it started cleanly
docker compose logs -f
```

`docker compose up -d --build` rebuilds the image only if the build context
(source, `pyproject.toml`, `poetry.lock`, `Dockerfile`) changed, then recreates
and restarts the container with the new image. Existing `.env` settings,
volumes (`./logs`), and container name are preserved.

### Using Docker Run

```bash
git pull
docker build -t goodwe2mqtt .
docker stop goodwe2mqtt && docker rm goodwe2mqtt
docker run -d \
  --name goodwe2mqtt \
  --network host \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  goodwe2mqtt
```

### Rolling Back

If the new version misbehaves, check out the previous commit/tag and repeat
the rebuild steps above:

```bash
git checkout <previous-commit-or-tag>
docker compose up -d --build
```

### Notes for this release (EMS Mode support)

- No new `.env` variables are required — EMS mode topics
  (`goodwe2mqtt/<serial>/ems_mode`, `/set/ems_mode`, `/set/ems_power_limit_watts`)
  are enabled automatically per configured inverter.
- See the [EMS Mode Usage Guide](ems_mode_usage.md) for how to use the new
  functionality once deployed.

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

### Polling Intervals

These apply to every inverter in the process (they are not per-inverter) and to every
family, ET and DT alike.

| Variable | Config Path | Default | Description |
|----------|-----------|---------|-------------|
| `G2M_MQTT_FAST_RUNTIME_DATA_INTERVAL_SECONDS` | `mqtt.fast_runtime_data_interval_seconds` | `1` | How often the inverter is polled. The same reading is also published to `.../fast_runtime_data`. |
| `G2M_MQTT_RUNTIME_DATA_INTERVAL_SECONDS` | `mqtt.runtime_data_interval_seconds` | `5` | How often the same reading is also published to `.../runtime_data`. Publication only; it does not cause extra reads. |

The read rate is set by the fast interval alone: the loop polls once per iteration and sleeps
until the next fast interval, so `1` means one poll per second. Setting the fast interval to `0`
does not stop polling — it skips the `.../fast_runtime_data` topic and the loop polls at the
runtime interval instead. A failed read retries after 5 seconds regardless of these settings.

### Inverter Overrides

For lists like inverters, use the index:
- `G2M_GOODWE_INVERTERS_0_IP_ADDRESS`
- `G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER`
- `G2M_GOODWE_INVERTERS_0_FAMILY` (optional; detected from the serial number when unset)

## Security

The container runs as a non-root user (`goodwe`) for improved security.
