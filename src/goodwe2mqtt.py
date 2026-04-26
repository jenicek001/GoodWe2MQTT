"""GoodWe2MQTT daemon module.

This module provides the core logic for connecting to GoodWe inverters and
publishing runtime data to an MQTT broker, while also handling remote
configuration commands via MQTT topics.
"""

import asyncio
import aiomqtt
import goodwe
import time
import copy
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import pytz
import tzlocal
import json
import sys
import os
import re
from logger import log
from goodwe.inverter import OperationMode
import sec1000s_protocol

config_file = ".env"

DEFAULT_CONFIG: Dict[str, Any] = {
    "mqtt": {
        "broker_ip": "",
        "broker_port": 1883,
        "username": "",
        "password": "",
        "client_id": "goodwe2mqtt",
        "topic_prefix": "goodwe2mqtt",
        "runtime_data_topic_postfix": "runtime_data",
        "runtime_data_interval_seconds": 5,
        "fast_runtime_data_topic_postfix": "fast_runtime_data",
        "fast_runtime_data_interval_seconds": 1,
        "control_topic_postfix": "control",
        "grid_export_limit_topic_postfix": "grid_export_limit",
    },
    "goodwe": {
        "inverters": []
    },
    "sec1000s": {
        "devices": []
    },
    "logger": {
        "log_file": "goodwe2mqtt.log",
        "log_level": "DEBUG",
        "log_to_console": True,
        "log_to_file": True,
        "log_rotate": True,
        "log_rotate_size": 1048576,
        "log_rotate_count": 5,
    },
    "influxdb": {
        "host": "",
        "port": 8086,
        "database": "openhab",
        "username": "",
        "password": "",
        "measurement": "goodwe",
    },
}


def _build_default_config() -> Dict[str, Any]:
    """Creates a deep copy of the default runtime configuration."""
    return copy.deepcopy(DEFAULT_CONFIG)

def override_config_from_env(config: Dict[str, Any], prefix: str = "G2M") -> None:
    """Recursively overrides configuration values from environment variables.
    
    Args:
        config: The configuration dictionary to update.
        prefix: The prefix for environment variables.
    """
    for key, value in config.items():
        if isinstance(value, dict):
            override_config_from_env(value, f"{prefix}_{key.upper()}")
        elif isinstance(value, list):
            # Handle list of items if needed, typically by index e.g. G2M_SECTION_0_KEY
            # For now, skipping list recursion or implementing basic index support
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    override_config_from_env(item, f"{prefix}_{key.upper()}_{i}")
        else:
            env_key = f"{prefix}_{key.upper()}"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                if isinstance(value, bool):
                    config[key] = env_val.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(value, int):
                    try:
                        config[key] = int(env_val)
                    except ValueError:
                        log.warning(f"Invalid integer for {env_key}: {env_val}")
                elif isinstance(value, float):
                    try:
                        config[key] = float(env_val)
                    except ValueError:
                        log.warning(f"Invalid float for {env_key}: {env_val}")
                else:
                    config[key] = env_val


def override_inverters_from_env(config: Dict[str, Any], prefix: str = "G2M") -> None:
    """Overrides inverter list from indexed environment variables."""
    inverter_pattern = re.compile(
        rf"^{re.escape(prefix)}_GOODWE_INVERTERS_(\d+)_(SERIAL_NUMBER|IP_ADDRESS)$"
    )
    inverters = config["goodwe"]["inverters"]

    for env_key, env_val in os.environ.items():
        match = inverter_pattern.match(env_key)
        if not match:
            continue

        index = int(match.group(1))
        field_name = match.group(2).lower()

        while len(inverters) <= index:
            inverters.append({"serial_number": "", "ip_address": ""})

        inverters[index][field_name] = env_val

def override_sec1000s_from_env(config: Dict[str, Any], prefix: str = "G2M") -> None:
    """Overrides SEC1000S device list from indexed environment variables."""
    sec_pattern = re.compile(
        rf"^{re.escape(prefix)}_SEC1000S_(\d+)"
        r"_(HOST|SERIAL_NUMBER|PORT|TIMEOUT|MIN_LIMIT_W|CONTRACTUAL_LIMIT_W"
        r"|CONTRACTUAL_SAFETY_MARGIN|SCAN_THREE_PHASES"
        r"|TELEMETRY_INTERVAL_SECONDS|GRID_EXPORT_LIMIT_INTERVAL_SECONDS"
        r"|SET_VERIFY_RETRIES|SET_VERIFY_DELAY_SECONDS)$"
    )
    devices = config["sec1000s"]["devices"]

    _defaults: Dict[str, Any] = {
        "host": "",
        "serial_number": "",
        "port": 1234,
        "timeout": 10.0,
        "min_limit_w": 100,
        "contractual_limit_w": 0,
        "contractual_safety_margin": 0.10,
        "scan_three_phases": False,
        "telemetry_interval_seconds": 5,
        "grid_export_limit_interval_seconds": 30,
        "set_verify_retries": 3,
        "set_verify_delay_seconds": 2.0,
    }

    for env_key, env_val in os.environ.items():
        match = sec_pattern.match(env_key)
        if not match:
            continue

        index = int(match.group(1))
        field_name = match.group(2).lower()

        while len(devices) <= index:
            devices.append(dict(_defaults))

        device = devices[index]
        default_val = _defaults.get(field_name)
        if isinstance(default_val, bool):
            device[field_name] = env_val.lower() in ("true", "1", "yes", "on")
        elif isinstance(default_val, int):
            try:
                device[field_name] = int(env_val)
            except ValueError:
                log.warning(f"Invalid integer for {env_key}: {env_val}")
        elif isinstance(default_val, float):
            try:
                device[field_name] = float(env_val)
            except ValueError:
                log.warning(f"Invalid float for {env_key}: {env_val}")
        else:
            device[field_name] = env_val

def dump_to_json(runtime_data: Dict[str, Any]) -> None:
    """Dumps runtime_data to a JSON file with a timestamped filename.

    Args:
        runtime_data: A dictionary containing the inverter runtime data.
    """
    current_time = datetime.now()
    inverter_runtime_data_json = json.dumps(runtime_data)
    log.debug(f'JSON: {inverter_runtime_data_json}')

    file_name = current_time.strftime("data/pv_inverter_status-%Y-%m-%d_%H-%M-%S.json")
    try:
        with open(file_name, 'w') as outfile:
            json.dump(runtime_data, outfile)
    except Exception as e:
        log.error(f"Failed to dump JSON to {file_name}: {e}")

def get_timezone_aware_local_time() -> datetime:
    """Gets the current local time as a timezone-aware datetime object.

    Returns:
        A timezone-aware datetime object representing the current local time.
    """
    now = datetime.now()
    timezone = tzlocal.get_localzone()
    local_time = pytz.timezone(str(timezone)).localize(now, is_dst=False)
    return local_time

class Goodwe_MQTT:
    """Handles communication between a GoodWe inverter and an MQTT broker."""

    def __init__(
        self,
        serial_number: str,
        ip_address: str,
        mqtt_broker_ip: str,
        mqtt_broker_port: int,
        mqtt_username: Optional[str],
        mqtt_password: Optional[str],
        mqtt_topic_prefix: str,
        mqtt_control_topic_postfix: str,
        mqtt_runtime_data_topic_postfix: str,
        mqtt_runtime_data_interval_seconds: int,
        mqtt_fast_runtime_data_topic_postfix: str,
        mqtt_fast_runtime_data_interval_seconds: int,
        mqtt_grid_export_limit_topic_postfix: str
    ) -> None:
        """Initializes the Goodwe_MQTT instance.

        Args:
            serial_number: Inverter serial number.
            ip_address: Inverter IP address.
            mqtt_broker_ip: MQTT broker IP address.
            mqtt_broker_port: MQTT broker port.
            mqtt_username: MQTT username.
            mqtt_password: MQTT password.
            mqtt_topic_prefix: Prefix for all MQTT topics.
            mqtt_control_topic_postfix: Postfix for the control topic.
            mqtt_runtime_data_topic_postfix: Postfix for the runtime data topic.
            mqtt_runtime_data_interval_seconds: Polling interval for regular data.
            mqtt_fast_runtime_data_topic_postfix: Postfix for fast runtime data.
            mqtt_fast_runtime_data_interval_seconds: Polling interval for fast data.
            mqtt_grid_export_limit_topic_postfix: Postfix for export limit topic.
        """
        self.serial_number = serial_number
        self.ip_address = ip_address

        self.mqtt_broker_ip = mqtt_broker_ip
        self.mqtt_broker_port = mqtt_broker_port
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password

        self.grid_export_limit: Optional[int] = None
        self.requested_grid_export_limit: Optional[int] = None

        mqtt_topic = f'{mqtt_topic_prefix}/{self.serial_number}'
        self.mqtt_topic_prefix = mqtt_topic_prefix
        self.mqtt_topic_base = mqtt_topic
        self.mqtt_control_topic = f'{mqtt_topic}/{mqtt_control_topic_postfix}'
        self.mqtt_set_topic_prefix = f'{mqtt_topic}/set'
        self.mqtt_set_topic_wildcard = f'{mqtt_topic}/set/+'
        self.mqtt_state_topic_prefix = f'{mqtt_topic}/state'
        self.mqtt_runtime_data_topic = f'{mqtt_topic}/{mqtt_runtime_data_topic_postfix}'
        self.mqtt_runtime_data_interval_seconds = timedelta(seconds=mqtt_runtime_data_interval_seconds)
        self.mqtt_fast_runtime_data_topic = f'{mqtt_topic}/{mqtt_fast_runtime_data_topic_postfix}'
        self.mqtt_fast_runtime_data_interval_seconds = timedelta(seconds=mqtt_fast_runtime_data_interval_seconds)
        self.grid_export_limit_topic = f'{mqtt_topic}/{mqtt_grid_export_limit_topic_postfix}'
        self.operation_mode_topic = f'{mqtt_topic}/operation_mode'
        self.status_topic = f'{mqtt_topic}/status'

        self.inverter: Any = None
        self.runtime_data: Optional[Dict[str, Any]] = None
        self.operation_mode: Optional[Any] = None

        log.info(str(self))

        self.mqtt_task = asyncio.ensure_future(self.mqtt_client_task())
        self.heartbeat_task_ref = asyncio.ensure_future(self.heartbeat_task())

    # Maps MQTT setting names → goodwe library setting IDs
    _INVERTER_SETTING_ALIAS: Dict[str, str] = {
        "grid_export_limit_watts": "grid_export_limit",
        "battery_charge_current_amps": "battery_charge_current",
    }

    def __str__(self) -> str:
        interval_rt = int(self.mqtt_runtime_data_interval_seconds.total_seconds())
        interval_fast = int(self.mqtt_fast_runtime_data_interval_seconds.total_seconds())
        return (
            f"Goodwe_MQTT {self.serial_number} init\n"
            f"  inverter:  ip={self.ip_address}\n"
            f"  broker:    ip={self.mqtt_broker_ip} port={self.mqtt_broker_port} user={self.mqtt_username}\n"
            f"  intervals: runtime_data={interval_rt}s  fast_runtime_data={interval_fast}s\n"
            f"  topics:    control={self.mqtt_control_topic}\n"
            f"             runtime_data={self.mqtt_runtime_data_topic}\n"
            f"             grid_export_limit={self.grid_export_limit_topic}"
        )

    async def heartbeat_task(self) -> None:
        """Periodically publishes an 'online' status to the MQTT broker."""
        log.info(f'heartbeat_task {self.serial_number} started')
        while True:
            try:
                async with aiomqtt.Client(
                    self.mqtt_broker_ip, self.mqtt_broker_port,
                    username=self.mqtt_username, password=self.mqtt_password
                ) as client:
                    log.info(f'heartbeat_task {self.serial_number} connected to MQTT broker')
                    while True:
                        log.debug(f'heartbeat_task {self.serial_number} sending heartbeat')
                        await client.publish(self.status_topic, payload=json.dumps("online"))
                        await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f'heartbeat_task {self.serial_number} error: {e}. Retrying in 10s...')
                await asyncio.sleep(10)

    async def connect_inverter(self) -> Optional[Any]:
        """Connects to the GoodWe inverter.

        Returns:
            The inverter object if connection is successful, None otherwise.
        """
        log.info(f'Connecting to inverter {self.serial_number} at {self.ip_address}')
        start_time = time.time()
        try:
            self.inverter = await goodwe.connect(host=self.ip_address, family='ET')
            connection_time = time.time() - start_time
            log.info(f'Connected to inverter {self.serial_number} in {connection_time} seconds')
            return self.inverter
        except Exception as e:
            log.error(f'Failed to connect to inverter {self.serial_number} at {self.ip_address}: {e}')
            self.inverter = None
            return None

    async def send_mqtt_export_limit(self, grid_export_limit: int) -> None:
        """Publishes the current grid export limit to MQTT.

        Args:
            grid_export_limit: The numeric limit to publish.
        """
        grid_export_limit_response = {
            'grid_export_limit_watts': grid_export_limit,
            'serial_number': self.serial_number,
            'last_seen': get_timezone_aware_local_time().isoformat()
        }
        await self.send_mqtt_response(self.grid_export_limit_topic, grid_export_limit_response)

    async def send_mqtt_response(self, topic: str, payload: Dict[str, Any]) -> None:
        """Sends a JSON-encoded payload to a specific MQTT topic.

        Args:
            topic: The MQTT topic to publish to.
            payload: The dictionary to be JSON-encoded and sent.
        """
        try:
            async with aiomqtt.Client(
                self.mqtt_broker_ip, self.mqtt_broker_port,
                username=self.mqtt_username, password=self.mqtt_password
            ) as client:
                log.debug(f'send_mqtt_response {self.serial_number} Publishing to {topic}: {payload}')
                await client.publish(topic, payload=json.dumps(payload))
        except Exception as e:
            log.error(f'send_mqtt_response {self.serial_number} MQTT sending error: {e}')

    async def mqtt_client_task(self) -> None:
        """Handles incoming control messages from the MQTT broker."""
        log.debug(f'mqtt_client_task: {self.serial_number}')

        while True:
            try:
                async with aiomqtt.Client(
                    self.mqtt_broker_ip, self.mqtt_broker_port,
                    username=self.mqtt_username, password=self.mqtt_password
                ) as client:
                    log.info(f'mqtt_client_task {self.serial_number} connected to MQTT broker')
                    await client.subscribe(self.mqtt_control_topic)
                    await client.subscribe(self.mqtt_set_topic_wildcard)
                    async for message in client.messages:
                        log.info(f'mqtt_client_task {self.serial_number} message received')
                        topic_str = str(message.topic)
                        payload = message.payload
                        if isinstance(payload, (bytes, bytearray)):
                            message_payload = payload.decode("utf-8")
                        else:
                            message_payload = str(payload)
                        log.info(f'mqtt_client_task {self.serial_number} topic: {topic_str} payload: {message_payload}')

                        # Handle /set/{setting_id} messages
                        set_prefix = f'{self.mqtt_set_topic_prefix}/'
                        if topic_str.startswith(set_prefix):
                            setting_id = topic_str[len(set_prefix):]
                            await self.handle_set_message(setting_id, message_payload)
                            continue

                        if 'get_grid_export_limit_watts' in message_payload:
                            log.info(f'mqtt_client_task {self.serial_number} Getting export limit')
                            self.grid_export_limit = await self.get_grid_export_limit()
                            if self.grid_export_limit is not None:
                                log.info(f'mqtt_client_task {self.serial_number} Got export limit: {self.grid_export_limit}')
                                await self.send_mqtt_export_limit(self.grid_export_limit)

                        elif 'set_grid_export_limit_watts' in message_payload:
                            try:
                                data = json.loads(message_payload)
                                self.requested_grid_export_limit = int(data['set_grid_export_limit_watts'])
                                log.info(f'mqtt_client_task {self.serial_number} Setting export limit: {self.requested_grid_export_limit}')
                                await self.set_grid_export_limit(self.requested_grid_export_limit)
                                self.grid_export_limit = await self.get_grid_export_limit()
                                if self.grid_export_limit is not None:
                                    log.info(f'mqtt_client_task {self.serial_number} Confirmed export limit: {self.grid_export_limit}')
                                    await self.send_mqtt_export_limit(self.grid_export_limit)
                            except (json.JSONDecodeError, KeyError, ValueError) as e:
                                log.error(f'mqtt_client_task {self.serial_number} Invalid payload: {e}')

                        elif 'get_operation_mode' in message_payload:
                            log.info(f'mqtt_client_task {self.serial_number} Getting operation mode')
                            await self.get_operation_mode()

                        elif 'set_eco_discharge_percent' in message_payload:
                            try:
                                data = json.loads(message_payload)
                                power = int(data['set_eco_discharge_percent'])
                                if 0 <= power <= 100:
                                    log.info(f'mqtt_client_task {self.serial_number} Setting eco discharge: {power}')
                                    await self.inverter.set_operation_mode(
                                        operation_mode=OperationMode.ECO_DISCHARGE, eco_mode_power=power
                                    )
                                    await self.get_operation_mode()
                                else:
                                    log.error(f'mqtt_client_task {self.serial_number} Invalid power: {power}')
                            except (json.JSONDecodeError, KeyError, ValueError) as e:
                                log.error(f'mqtt_client_task {self.serial_number} Invalid payload: {e}')

                        elif 'set_eco_charge_percent' in message_payload:
                            try:
                                data = json.loads(message_payload)
                                power = int(data['set_eco_charge_percent'])
                                soc = int(data['target_battery_soc_percent'])
                                if 0 <= power <= 100 and 0 <= soc <= 100:
                                    log.info(f'mqtt_client_task {self.serial_number} Setting eco charge: {power}, SoC: {soc}')
                                    await self.inverter.set_operation_mode(
                                        operation_mode=OperationMode.ECO_CHARGE, eco_mode_power=power, eco_mode_soc=soc
                                    )
                                    await self.get_operation_mode()
                                else:
                                    log.error(f'mqtt_client_task {self.serial_number} Invalid params: {power}, {soc}')
                            except (json.JSONDecodeError, KeyError, ValueError) as e:
                                log.error(f'mqtt_client_task {self.serial_number} Invalid payload: {e}')

                        elif 'set_general_operation_mode' in message_payload:
                            log.info(f'mqtt_client_task {self.serial_number} Setting general mode')
                            try:
                                await self.inverter.set_operation_mode(operation_mode=OperationMode.GENERAL)
                                await self.get_operation_mode()
                            except Exception as e:
                                log.error(f'mqtt_client_task {self.serial_number} Error: {e}')

                        else:
                            log.error(f'mqtt_client_task {self.serial_number} Invalid command: {message_payload}')
            
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f'mqtt_client_task {self.serial_number} MQTT error: {e}. Reconnecting in 5s...')
                await asyncio.sleep(5)

    # Work mode name → integer value mapping (GoodWe ET series)
    WORK_MODE_OPTIONS: Dict[str, int] = {
        "General mode": 0,
        "Off grid mode": 1,
        "Backup mode": 2,
        "Eco mode": 4,
    }

    async def write_setting(self, setting_id: str, value: Any, retries: int = 3) -> bool:
        """Writes a setting to the inverter with exponential-backoff retry logic.

        Args:
            setting_id: The inverter setting identifier.
            value: The value to write.
            retries: Maximum number of attempts.

        Returns:
            True if the write succeeded, False otherwise.
        """
        for attempt in range(1, retries + 1):
            log.info(f'write_setting {self.serial_number} attempt {attempt}/{retries}: {setting_id}={value}')
            try:
                await self.inverter.write_setting(setting_id, value)
                log.info(f'write_setting {self.serial_number} success: {setting_id}={value}')
                return True
            except Exception as e:
                log.error(f'write_setting {self.serial_number} attempt {attempt} failed: {e}')
                if attempt < retries:
                    backoff = 2 ** (attempt - 1)
                    log.info(f'write_setting {self.serial_number} retrying in {backoff}s...')
                    await asyncio.sleep(backoff)
        log.error(f'write_setting {self.serial_number} all {retries} attempts failed for {setting_id}')
        return False

    async def handle_set_message(self, setting_id: str, payload_str: str) -> None:
        """Handles a message received on a /set/{setting_id} topic.

        Parses the payload, writes the setting to the inverter, reads it back,
        and publishes the updated value on the corresponding state topic.

        Args:
            setting_id: The inverter setting identifier extracted from the topic.
            payload_str: Raw string payload from the MQTT message.
        """
        log.info(f'handle_set_message {self.serial_number} setting_id={setting_id} payload={payload_str}')
        payload_str = payload_str.strip()
        inverter_setting_id = self._INVERTER_SETTING_ALIAS.get(setting_id, setting_id)

        # Determine the value to write
        if setting_id == 'work_mode':
            if payload_str in self.WORK_MODE_OPTIONS:
                value: Any = self.WORK_MODE_OPTIONS[payload_str]
            else:
                try:
                    value = int(payload_str)
                except ValueError:
                    log.error(f'handle_set_message {self.serial_number} invalid work_mode value: {payload_str}')
                    return
        else:
            try:
                # Prefer integer, fall back to float, then string
                value = int(payload_str)
            except ValueError:
                try:
                    value = float(payload_str)
                except ValueError:
                    log.warning(
                        f'handle_set_message {self.serial_number} unexpected string payload '
                        f'for {setting_id}: {payload_str!r}'
                    )
                    value = payload_str

        success = await self.write_setting(inverter_setting_id, value)
        if success:
            # Read back and publish the updated state
            try:
                current_value = await self.inverter.read_setting(inverter_setting_id)
                state_topic = f'{self.mqtt_state_topic_prefix}/{setting_id}'
                await self.send_mqtt_response(state_topic, {setting_id: current_value})
                log.info(f'handle_set_message {self.serial_number} published state {setting_id}={current_value}')
            except Exception as e:
                log.error(f'handle_set_message {self.serial_number} read-back failed for {setting_id}: {e}')

    async def publish_ha_discovery(self) -> None:
        """Publishes Home Assistant MQTT Discovery payloads for controllable entities."""
        sn = self.serial_number
        base = self.mqtt_topic_base
        device = {
            "identifiers": [sn],
            "name": f"GoodWe Inverter {sn}",
            "manufacturer": "GoodWe",
            "model": "ET series",
        }

        entities: List[Dict[str, Any]] = [
            # work_mode – select
            {
                "component": "select",
                "unique_id": f"{sn}_work_mode",
                "name": "Operation Mode",
                "command_topic": f"{base}/set/work_mode",
                "state_topic": f"{base}/state/work_mode",
                "value_template": "{{ value_json.work_mode }}",
                "options": list(self.WORK_MODE_OPTIONS.keys()),
                "device": device,
            },
            # battery_charge_current_amps – number
            {
                "component": "number",
                "unique_id": f"{sn}_battery_charge_current_amps",
                "name": "Battery Charge Current",
                "command_topic": f"{base}/set/battery_charge_current_amps",
                "state_topic": f"{base}/state/battery_charge_current_amps",
                "value_template": "{{ value_json.battery_charge_current_amps }}",
                "unit_of_measurement": "A",
                "min": 0,
                "max": 25,
                "step": 1,
                "device": device,
            },
            # grid_export_limit_watts – number
            {
                "component": "number",
                "unique_id": f"{sn}_grid_export_limit_watts",
                "name": "Grid Export Limit",
                "command_topic": f"{base}/set/grid_export_limit_watts",
                "state_topic": f"{base}/state/grid_export_limit_watts",
                "value_template": "{{ value_json.grid_export_limit_watts }}",
                "unit_of_measurement": "W",
                "min": 0,
                "max": 10000,
                "step": 1,
                "device": device,
            },
        ]

        for entity in entities:
            component = entity.pop("component")
            unique_id = entity["unique_id"]
            discovery_topic = f"homeassistant/{component}/{unique_id}/config"
            log.info(f'publish_ha_discovery {sn} publishing {discovery_topic}')
            await self.send_mqtt_response(discovery_topic, entity)

    async def get_grid_export_limit(self) -> Optional[int]:
        """Reads the current grid export limit from the inverter.

        Returns:
            The numeric export limit or None if read fails.
        """
        try:
            raw = await self.inverter.get_grid_export_limit()
            # The goodwe library returns an unsigned 16-bit register value; reinterpret as signed.
            if isinstance(raw, int) and raw >= 0x8000:
                raw = raw - 0x10000
            self.grid_export_limit = raw
            log.debug(f'get_grid_export_limit {self.serial_number}: {self.grid_export_limit}')
            return self.grid_export_limit
        except Exception as e:
            log.error(f'get_grid_export_limit {self.serial_number} failed: {e}')
            return None

    async def set_grid_export_limit(self, requested_grid_export_limit: int) -> None:
        """Sets the grid export limit on the inverter.

        Args:
            requested_grid_export_limit: The numeric limit to set.
        """
        try:
            await self.inverter.set_grid_export_limit(requested_grid_export_limit)
            log.debug(f'set_grid_export_limit {self.serial_number}: {requested_grid_export_limit}')
            self.requested_grid_export_limit = requested_grid_export_limit
        except Exception as e:
            log.error(f'set_grid_export_limit {self.serial_number} failed: {e}')

    async def get_ongrid_battery_dod(self) -> None:
        """Reads the on-grid battery Depth of Discharge (DoD) from the inverter."""
        try:
            dod = await self.inverter.get_ongrid_battery_dod()
            log.debug(f'get_ongrid_battery_dod {self.serial_number}: {dod}')
        except Exception as e:
            log.error(f'get_ongrid_battery_dod {self.serial_number} failed: {e}')

    async def get_operation_mode(self) -> Optional[Any]:
        """Reads the current operation mode from the inverter and publishes it to MQTT.

        Returns:
            The operation mode object or None if read fails.
        """
        log.info(f'get_operation_mode {self.serial_number} requesting...')
        try:
            self.operation_mode = await self.inverter.get_operation_mode()
            log.info(f'get_operation_mode {self.serial_number} current: {self.operation_mode}')

            response = {
                'operation_mode': self.operation_mode,
                'serial_number': self.serial_number,
                'last_seen': get_timezone_aware_local_time().isoformat()
            }
            await self.send_mqtt_response(self.operation_mode_topic, response)
            return self.operation_mode
        except Exception as e:
            log.error(f'get_operation_mode {self.serial_number} failed: {e}')
            return None

    async def read_runtime_data(self) -> Optional[Dict[str, Any]]:
        """Reads real-time data from the inverter.

        Returns:
            A dictionary containing runtime data or None if read fails.
        """
        start_time = time.time()
        try:
            self.runtime_data = await self.inverter.read_runtime_data()
            if self.runtime_data:
                # Replace timestamp object with ISO string for JSON serialization
                if 'timestamp' in self.runtime_data:
                    self.runtime_data['timestamp'] = self.runtime_data['timestamp'].isoformat()
                
                self.runtime_data['serial_number'] = self.serial_number
                self.runtime_data['last_seen'] = get_timezone_aware_local_time().isoformat()
                self.runtime_data['request_processing_time'] = time.time() - start_time
                return self.runtime_data
            return None
        except Exception as e:
            log.error(f'read_runtime_data {self.serial_number} failed: {e}')
            return None

    async def read_device_info(self) -> Optional[Any]:
        """Reads static device information from the inverter.

        Returns:
            Device info object or None if read fails.
        """
        try:
            info = await self.inverter.read_device_info()
            log.debug(f'read_device_info {self.serial_number}: {info}')
            return info
        except Exception as e:
            log.error(f'read_device_info {self.serial_number} failed: {e}')
            return None

    async def read_settings_data(self) -> Optional[Any]:
        """Reads inverter settings data.

        Returns:
            Settings object or None if read fails.
        """
        try:
            settings = await self.inverter.read_settings_data()
            supported = {k: v for k, v in settings.items() if v is not None}
            log.info(
                f'read_settings_data {self.serial_number}: '
                f'{len(supported)}/{len(settings)} settings supported: '
                f'{json.dumps(supported, default=str)}'
            )
            return settings
        except Exception as e:
            log.error(f'read_settings_data {self.serial_number} failed: {e}')
            return None

    async def main_loop(self) -> None:
        """The main polling loop for retrieving and publishing inverter data."""
        while True:
            try:
                # Check Inverter Connection
                if self.inverter is None:
                    log.info(f'main_loop {self.serial_number} Inverter not connected. Attempting...')
                    await self.connect_inverter()
                    if self.inverter is None:
                        log.warning(f'main_loop {self.serial_number} Connection failed. Retrying in 10s...')
                        await asyncio.sleep(10)
                        continue

                log.debug(f'main_loop {self.serial_number} requesting settings')
                if await self.read_settings_data() is None:
                    log.warning(f'main_loop {self.serial_number} Failed to read settings. Retrying in 5s...')
                    await asyncio.sleep(5)
                    continue

                next_fast_runtime_data_time = datetime.now()
                next_runtime_data_time = datetime.now()

                async with aiomqtt.Client(
                    self.mqtt_broker_ip, self.mqtt_broker_port,
                    username=self.mqtt_username, password=self.mqtt_password
                ) as client:
                    log.info(f'main_loop {self.serial_number} connected to MQTT broker')

                    while True:
                        now = datetime.now()
                        if self.mqtt_fast_runtime_data_interval_seconds.total_seconds() > 0:
                            next_fast_runtime_data_time = now + self.mqtt_fast_runtime_data_interval_seconds
                        else:
                            next_fast_runtime_data_time = now + self.mqtt_runtime_data_interval_seconds
                        
                        log.debug(f'main_loop {self.serial_number} reading runtime data')
                        data = await self.read_runtime_data()
                        if data is None:
                            log.warning(f'main_loop {self.serial_number} Failed to read data. Retrying in 5s...')
                            await asyncio.sleep(5)
                            continue

                        # Publish fast runtime data (disabled when interval is 0)
                        if self.mqtt_fast_runtime_data_interval_seconds.total_seconds() > 0:
                            await client.publish(self.mqtt_fast_runtime_data_topic, payload=json.dumps(data))

                        # Publish regular runtime data if interval reached
                        if now >= next_runtime_data_time:
                            next_runtime_data_time = now + self.mqtt_runtime_data_interval_seconds
                            await client.publish(self.mqtt_runtime_data_topic, payload=json.dumps(data))

                        now = datetime.now()
                        if now < next_fast_runtime_data_time:
                            sleep_time = (next_fast_runtime_data_time - now).total_seconds()
                            await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                log.info(f'main_loop {self.serial_number} cancelled.')
                break
            except KeyboardInterrupt:
                log.error(f'Goodwe_MQTT {self.serial_number} interrupted.')
                break
            except Exception as e:
                log.error(f'Goodwe_MQTT {self.serial_number} main_loop exception: {e}. Retrying in 5s...')
                await asyncio.sleep(5)

class SEC1000S_MQTT:
    """Manages a GoodWe SEC1000S energy controller via MQTT."""

    def __init__(
        self,
        serial_number: str,
        host: str,
        port: int,
        timeout: float,
        min_limit_w: int,
        contractual_limit_w: int,
        contractual_safety_margin: float,
        scan_three_phases: bool,
        telemetry_interval_seconds: int,
        grid_export_limit_interval_seconds: int,
        set_verify_retries: int,
        set_verify_delay_seconds: float,
        mqtt_broker_ip: str,
        mqtt_broker_port: int,
        mqtt_username: Optional[str],
        mqtt_password: Optional[str],
        mqtt_topic_prefix: str,
    ) -> None:
        self.serial_number = serial_number
        self.host = host
        self.port = port
        self.timeout = timeout
        self.min_limit_w = min_limit_w
        self.contractual_limit_w = contractual_limit_w
        self.effective_ceiling_w = int(contractual_limit_w * (1.0 - contractual_safety_margin))
        self.scan_three_phases = scan_three_phases
        self.telemetry_interval_seconds = telemetry_interval_seconds
        self.grid_export_limit_interval_seconds = grid_export_limit_interval_seconds
        self.set_verify_retries = set_verify_retries
        self.set_verify_delay_seconds = set_verify_delay_seconds

        self.mqtt_broker_ip = mqtt_broker_ip
        self.mqtt_broker_port = mqtt_broker_port
        self.mqtt_username = mqtt_username
        self.mqtt_password = mqtt_password
        self.contractual_safety_margin = contractual_safety_margin

        base = f"{mqtt_topic_prefix}/sec1000s/{serial_number}"
        self.mqtt_topic_base = base
        self.telemetry_topic = f"{base}/telemetry"
        self.grid_export_limit_topic = f"{base}/grid_export_limit"
        self.status_topic = f"{base}/status"
        self.control_topic = f"{base}/control"

        log.info(str(self))

        self.mqtt_task = asyncio.ensure_future(self.mqtt_client_task())
        self.heartbeat_task_ref = asyncio.ensure_future(self.heartbeat_task())
        self.telemetry_task_ref = asyncio.ensure_future(self.telemetry_loop())
        self.grid_export_limit_task_ref = asyncio.ensure_future(self.grid_export_limit_loop())

    def __str__(self) -> str:
        margin_pct = int(self.contractual_safety_margin * 100)
        return (
            f"SEC1000S_MQTT {self.serial_number} init\n"
            f"  device:    host={self.host} port={self.port} timeout={self.timeout}s\n"
            f"  limits:    floor={self.min_limit_w}W  ceiling={self.effective_ceiling_w}W"
            f" (contractual={self.contractual_limit_w}W margin={margin_pct}%)\n"
            f"  broker:    ip={self.mqtt_broker_ip} port={self.mqtt_broker_port} user={self.mqtt_username}\n"
            f"  intervals: telemetry={self.telemetry_interval_seconds}s"
            f"  grid_export_limit={self.grid_export_limit_interval_seconds}s\n"
            f"  settings:  scan_three_phases={str(self.scan_three_phases).lower()}"
            f" retries={self.set_verify_retries} verify_delay={self.set_verify_delay_seconds}s\n"
            f"  topics:    control={self.control_topic}\n"
            f"             telemetry={self.telemetry_topic}\n"
            f"             grid_export_limit={self.grid_export_limit_topic}"
        )

    async def heartbeat_task(self) -> None:
        """Periodically publishes 'online' status to the MQTT broker."""
        log.info(f"sec1000s heartbeat_task {self.serial_number} started")
        while True:
            try:
                async with aiomqtt.Client(
                    self.mqtt_broker_ip, self.mqtt_broker_port,
                    username=self.mqtt_username, password=self.mqtt_password
                ) as client:
                    log.info(f"sec1000s heartbeat_task {self.serial_number} connected")
                    while True:
                        await client.publish(self.status_topic, payload=json.dumps("online"))
                        await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"sec1000s heartbeat_task {self.serial_number} error: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

    async def telemetry_loop(self) -> None:
        """Periodically polls telemetry from the SEC1000S and publishes to MQTT."""
        log.info(f"sec1000s telemetry_loop {self.serial_number} started")
        while True:
            try:
                data = await sec1000s_protocol.get_telemetry(self.host, self.port, self.timeout)
                data["serial_number"] = self.serial_number
                data["last_seen"] = get_timezone_aware_local_time().isoformat()
                await self.send_mqtt_response(self.telemetry_topic, data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"sec1000s telemetry_loop {self.serial_number} error: {e}")
            try:
                await asyncio.sleep(self.telemetry_interval_seconds)
            except asyncio.CancelledError:
                break

    async def grid_export_limit_loop(self) -> None:
        """Periodically polls grid export limit status and publishes to MQTT."""
        log.info(f"sec1000s grid_export_limit_loop {self.serial_number} started")
        while True:
            try:
                data = await sec1000s_protocol.get_grid_export_limit(self.host, self.port, self.timeout)
                data["serial_number"] = self.serial_number
                data["effective_ceiling_watts"] = self.effective_ceiling_w
                data["last_seen"] = get_timezone_aware_local_time().isoformat()
                await self.send_mqtt_response(self.grid_export_limit_topic, data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"sec1000s grid_export_limit_loop {self.serial_number} error: {e}")
            try:
                await asyncio.sleep(self.grid_export_limit_interval_seconds)
            except asyncio.CancelledError:
                break

    async def mqtt_client_task(self) -> None:
        """Handles incoming control messages from the MQTT broker."""
        log.debug(f"sec1000s mqtt_client_task {self.serial_number}")
        while True:
            try:
                async with aiomqtt.Client(
                    self.mqtt_broker_ip, self.mqtt_broker_port,
                    username=self.mqtt_username, password=self.mqtt_password
                ) as client:
                    log.info(f"sec1000s mqtt_client_task {self.serial_number} connected")
                    await client.subscribe(self.control_topic)
                    try:
                        startup_data = await sec1000s_protocol.get_grid_export_limit(
                            self.host, self.port, self.timeout
                        )
                        log.info(
                            f"sec1000s mqtt_client_task {self.serial_number} startup grid_export_limit: "
                            f"{startup_data.get('grid_export_limit_watts')}W "
                            f"(total_capacity={startup_data.get('total_capacity_watts')}W, "
                            f"control_mode={startup_data.get('control_mode')}, "
                            f"ratio_ct_raw={startup_data.get('ratio_ct_raw')})"
                        )
                    except Exception as e:
                        log.error(
                            f"sec1000s mqtt_client_task {self.serial_number} startup read failed: {e}"
                        )
                    async for message in client.messages:
                        payload = message.payload
                        if isinstance(payload, (bytes, bytearray)):
                            message_payload = payload.decode("utf-8")
                        else:
                            message_payload = str(payload)
                        log.info(
                            f"sec1000s mqtt_client_task {self.serial_number} "
                            f"topic={message.topic} payload={message_payload}"
                        )

                        if "set_grid_export_limit_watts" in message_payload:
                            try:
                                data = json.loads(message_payload)
                                limit_w = int(data["set_grid_export_limit_watts"])
                                await self.set_grid_export_limit_with_verify(limit_w)
                            except (json.JSONDecodeError, KeyError, ValueError) as e:
                                log.error(
                                    f"sec1000s mqtt_client_task {self.serial_number} invalid payload: {e}"
                                )
                        elif "get_grid_export_limit" in message_payload:
                            try:
                                data = await sec1000s_protocol.get_grid_export_limit(
                                    self.host, self.port, self.timeout
                                )
                                data["effective_ceiling_watts"] = self.effective_ceiling_w
                                data["last_seen"] = get_timezone_aware_local_time().isoformat()
                                await self.send_mqtt_response(self.grid_export_limit_topic, data)
                            except Exception as e:
                                log.error(
                                    f"sec1000s mqtt_client_task {self.serial_number} "
                                    f"get_grid_export_limit failed: {e}"
                                )
                        elif "get_telemetry" in message_payload:
                            try:
                                data = await sec1000s_protocol.get_telemetry(
                                    self.host, self.port, self.timeout
                                )
                                data["last_seen"] = get_timezone_aware_local_time().isoformat()
                                await self.send_mqtt_response(self.telemetry_topic, data)
                            except Exception as e:
                                log.error(
                                    f"sec1000s mqtt_client_task {self.serial_number} "
                                    f"get_telemetry failed: {e}"
                                )
                        else:
                            log.error(
                                f"sec1000s mqtt_client_task {self.serial_number} "
                                f"unknown command: {message_payload}"
                            )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(
                    f"sec1000s mqtt_client_task {self.serial_number} MQTT error: {e}. "
                    "Reconnecting in 5s..."
                )
                await asyncio.sleep(5)

    async def set_grid_export_limit_with_verify(self, limit_w: int) -> None:
        """Set grid export limit with safety checks and readback verification.

        Steps:
          1. Reject if ``limit_w < min_limit_w`` (safety floor).
          2. Clamp silently to ``effective_ceiling_w`` if above ceiling.
          3. Read current total_capacity from device.
          4. Call ``set_grid_export_limit`` then ``enable_value_mode`` to activate.
          5. Readback after delay; retry up to ``set_verify_retries`` times.
        """
        if limit_w < self.min_limit_w:
            log.error(
                f"sec1000s {self.serial_number} set_grid_export_limit_with_verify: "
                f"limit {limit_w}W is below safety floor {self.min_limit_w}W — rejecting"
            )
            await self.send_mqtt_response(self.grid_export_limit_topic, {
                "error": (
                    f"limit {limit_w}W is below safety floor {self.min_limit_w}W"
                ),
                "last_seen": get_timezone_aware_local_time().isoformat(),
            })
            return

        if limit_w > self.effective_ceiling_w:
            log.info(
                f"sec1000s {self.serial_number} clamping {limit_w}W "
                f"to effective ceiling {self.effective_ceiling_w}W "
                f"(contractual={self.contractual_limit_w}W)"
            )
            limit_w = self.effective_ceiling_w

        for attempt in range(1, self.set_verify_retries + 1):
            log.info(
                f"sec1000s {self.serial_number} set_grid_export_limit attempt "
                f"{attempt}/{self.set_verify_retries}: {limit_w}W"
            )
            try:
                current = await sec1000s_protocol.get_grid_export_limit(
                    self.host, self.port, self.timeout
                )
                total_capacity_w = current.get("total_capacity_watts", 0)
                if total_capacity_w <= 0:
                    log.warning(
                        f"sec1000s {self.serial_number} total_capacity_watts={total_capacity_w}, "
                        "defaulting to 10000W"
                    )
                    total_capacity_w = 10000

                set_ack = await sec1000s_protocol.set_grid_export_limit(
                    self.host, self.port, self.timeout,
                    limit_watts=limit_w,
                    total_capacity_watts=total_capacity_w,
                    scan_three_phases=self.scan_three_phases,
                )
                if set_ack is False:
                    raise RuntimeError(
                        f"sec1000s {self.serial_number} did not acknowledge set_grid_export_limit"
                    )

                enable_ack = await sec1000s_protocol.enable_value_mode(
                    self.host, self.port, self.timeout
                )
                if enable_ack is False:
                    raise RuntimeError(
                        f"sec1000s {self.serial_number} did not acknowledge enable_value_mode"
                    )
                await asyncio.sleep(self.set_verify_delay_seconds)

                readback = await sec1000s_protocol.get_grid_export_limit(
                    self.host, self.port, self.timeout
                )
                readback_w = readback.get("grid_export_limit_watts", -1)

                if abs(readback_w - limit_w) < 50:
                    log.info(
                        f"sec1000s {self.serial_number} grid export limit confirmed: {readback_w}W"
                    )
                    readback["effective_ceiling_watts"] = self.effective_ceiling_w
                    readback["last_seen"] = get_timezone_aware_local_time().isoformat()
                    await self.send_mqtt_response(self.grid_export_limit_topic, readback)
                    return

                log.warning(
                    f"sec1000s {self.serial_number} readback mismatch: "
                    f"requested {limit_w}W, got {readback_w}W"
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(
                    f"sec1000s {self.serial_number} set_grid_export_limit attempt {attempt} error: {e}"
                )

        log.error(
            f"sec1000s {self.serial_number} failed to confirm grid export limit "
            f"after {self.set_verify_retries} attempts"
        )
        await self.send_mqtt_response(self.grid_export_limit_topic, {
            "error": (
                f"failed to set grid export limit to {limit_w}W "
                f"after {self.set_verify_retries} attempts"
            ),
            "last_seen": get_timezone_aware_local_time().isoformat(),
        })

    async def send_mqtt_response(self, topic: str, payload: Dict[str, Any]) -> None:
        """Sends a JSON-encoded payload to a specific MQTT topic."""
        try:
            async with aiomqtt.Client(
                self.mqtt_broker_ip, self.mqtt_broker_port,
                username=self.mqtt_username, password=self.mqtt_password
            ) as client:
                log.debug(f"sec1000s {self.serial_number} send_mqtt_response {topic}: {payload}")
                await client.publish(topic, payload=json.dumps(payload))
        except Exception as e:
            log.error(f"sec1000s {self.serial_number} send_mqtt_response error: {e}")

    async def publish_ha_discovery(self) -> None:
        """Publishes Home Assistant MQTT Discovery payload for export limit control."""
        name = self.serial_number
        base = self.mqtt_topic_base
        device = {
            "identifiers": [f"sec1000s_{name}"],
            "name": f"SEC1000S {name}",
            "manufacturer": "GoodWe",
            "model": "SEC1000S",
        }
        entity = {
            "unique_id": f"sec1000s_{name}_grid_export_limit_watts",
            "name": "Grid Export Limit",
            "command_topic": f"{base}/control",
            "state_topic": f"{base}/grid_export_limit",
            "value_template": "{{ value_json.grid_export_limit_watts }}",
            "unit_of_measurement": "W",
            "min": self.min_limit_w,
            "max": self.effective_ceiling_w,
            "step": 100,
            "device": device,
        }
        discovery_topic = f"homeassistant/number/{entity['unique_id']}/config"
        log.info(f"sec1000s {name} publish_ha_discovery {discovery_topic}")
        await self.send_mqtt_response(discovery_topic, entity)


async def main(config: Dict[str, Any]) -> None:
    """Entry point for starting the daemon with multiple inverters.

    Args:
        config: Loaded configuration dictionary.
    """
    inverters: List[Goodwe_MQTT] = []
    log.info(f'Goodwe2MQTT starting with {len(config["goodwe"]["inverters"])} inverters')

    for inverter_config in config["goodwe"]["inverters"]:
        inv = Goodwe_MQTT(
            serial_number=inverter_config["serial_number"],
            ip_address=inverter_config["ip_address"],
            mqtt_broker_ip=config["mqtt"]["broker_ip"],
            mqtt_broker_port=config["mqtt"]["broker_port"],
            mqtt_username=config["mqtt"].get("username"),
            mqtt_password=config["mqtt"].get("password"),
            mqtt_topic_prefix=config["mqtt"]["topic_prefix"],
            mqtt_control_topic_postfix=config["mqtt"]["control_topic_postfix"],
            mqtt_runtime_data_topic_postfix=config["mqtt"]["runtime_data_topic_postfix"],
            mqtt_runtime_data_interval_seconds=config["mqtt"]["runtime_data_interval_seconds"],
            mqtt_fast_runtime_data_topic_postfix=config["mqtt"]["fast_runtime_data_topic_postfix"],
            mqtt_fast_runtime_data_interval_seconds=config["mqtt"]["fast_runtime_data_interval_seconds"],
            mqtt_grid_export_limit_topic_postfix=config["mqtt"]["grid_export_limit_topic_postfix"]
        )

        await inv.connect_inverter()
        inverters.append(inv)
        asyncio.ensure_future(inv.main_loop())

        # Distribute communication load
        await asyncio.sleep(config["mqtt"]["fast_runtime_data_interval_seconds"] / 2.0)

    # Spawn SEC1000S device instances
    sec1000s_devices: List[SEC1000S_MQTT] = []
    for sec_cfg in config.get("sec1000s", {}).get("devices", []):
        if not sec_cfg.get("host") or not sec_cfg.get("serial_number"):
            log.warning(f'main skipping SEC1000S device with missing host/serial_number: {sec_cfg}')
            continue
        if not sec_cfg.get("contractual_limit_w"):
            log.warning(
                f'main skipping SEC1000S device {sec_cfg.get("serial_number")!r}: '
                "contractual_limit_w is not set"
            )
            continue
        sec = SEC1000S_MQTT(
            serial_number=sec_cfg["serial_number"],
            host=sec_cfg["host"],
            port=sec_cfg["port"],
            timeout=sec_cfg["timeout"],
            min_limit_w=sec_cfg["min_limit_w"],
            contractual_limit_w=sec_cfg["contractual_limit_w"],
            contractual_safety_margin=sec_cfg["contractual_safety_margin"],
            scan_three_phases=sec_cfg["scan_three_phases"],
            telemetry_interval_seconds=sec_cfg["telemetry_interval_seconds"],
            grid_export_limit_interval_seconds=sec_cfg["grid_export_limit_interval_seconds"],
            set_verify_retries=sec_cfg["set_verify_retries"],
            set_verify_delay_seconds=sec_cfg["set_verify_delay_seconds"],
            mqtt_broker_ip=config["mqtt"]["broker_ip"],
            mqtt_broker_port=config["mqtt"]["broker_port"],
            mqtt_username=config["mqtt"].get("username"),
            mqtt_password=config["mqtt"].get("password"),
            mqtt_topic_prefix=config["mqtt"]["topic_prefix"],
        )
        sec1000s_devices.append(sec)
        log.info(f'main spawned SEC1000S_MQTT {sec_cfg["serial_number"]}')

    # Gather tasks to keep main running
    tasks = [inv.mqtt_task for inv in inverters] + [inv.heartbeat_task_ref for inv in inverters]
    tasks += [sec.mqtt_task for sec in sec1000s_devices]
    tasks += [sec.heartbeat_task_ref for sec in sec1000s_devices]
    tasks += [sec.telemetry_task_ref for sec in sec1000s_devices]
    tasks += [sec.grid_export_limit_task_ref for sec in sec1000s_devices]
    await asyncio.gather(*tasks)

def read_config(file_path: str) -> Dict[str, Any]:
    """Builds configuration from defaults and environment variables.

    Args:
        file_path: Unused, kept for backwards-compatible function signature.

    Returns:
        The loaded configuration dictionary.
    """
    try:
        config = _build_default_config()
        override_config_from_env(config)
        override_inverters_from_env(config)
        override_sec1000s_from_env(config)

        if not config["goodwe"]["inverters"]:
            log.error(
                "No inverters configured. Set G2M_GOODWE_INVERTERS_<index>_SERIAL_NUMBER "
                "and G2M_GOODWE_INVERTERS_<index>_IP_ADDRESS."
            )
            sys.exit(1)

        for inverter in config["goodwe"]["inverters"]:
            if not inverter.get("serial_number") or not inverter.get("ip_address"):
                log.error(
                    "Each inverter must define both serial_number and ip_address "
                    "via G2M_GOODWE_INVERTERS_<index>_* environment variables."
                )
                sys.exit(1)

        return config
    except Exception as e:
        log.error(f'Error loading configuration from environment: {e}')
        sys.exit(1)

if __name__ == '__main__':
    # Start the daemon
    _config = read_config(config_file)
    asyncio.run(main(_config))
