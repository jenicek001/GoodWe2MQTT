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
    GRID_EXPORT_LIMIT_MIN_WATTS = 1
    GRID_EXPORT_LIMIT_MAX_WATTS = 10000

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

    def __str__(self) -> str:
        return (f'{self.serial_number}, {self.ip_address}, {self.grid_export_limit}, '
                f'{self.mqtt_broker_ip}, {self.mqtt_broker_port}, {self.mqtt_username}, '
                f'{self.mqtt_control_topic}, {self.mqtt_runtime_data_topic}, '
                f'{self.grid_export_limit_topic}')

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
            'grid_export_limit': grid_export_limit,
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

                        if 'get_grid_export_limit' in message_payload:
                            log.info(f'mqtt_client_task {self.serial_number} Getting export limit')
                            self.grid_export_limit = await self.get_grid_export_limit()
                            if self.grid_export_limit is not None:
                                log.info(f'mqtt_client_task {self.serial_number} Got export limit: {self.grid_export_limit}')
                                await self.send_mqtt_export_limit(self.grid_export_limit)

                        elif 'set_grid_export_limit' in message_payload:
                            try:
                                data = json.loads(message_payload)
                                self.requested_grid_export_limit = int(data['set_grid_export_limit'])
                                if not self.is_valid_grid_export_limit(self.requested_grid_export_limit):
                                    log.error(
                                        f'mqtt_client_task {self.serial_number} refusing invalid '
                                        f'export limit (W): {self.requested_grid_export_limit}. '
                                        f'Allowed range: {self.GRID_EXPORT_LIMIT_MIN_WATTS}-'
                                        f'{self.GRID_EXPORT_LIMIT_MAX_WATTS}'
                                    )
                                    continue
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

                        elif 'set_eco_discharge' in message_payload:
                            try:
                                data = json.loads(message_payload)
                                power = int(data['set_eco_discharge'])
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

                        elif 'set_eco_charge' in message_payload:
                            try:
                                data = json.loads(message_payload)
                                power = int(data['set_eco_charge'])
                                soc = int(data['target_battery_soc'])
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

    def is_valid_grid_export_limit(self, grid_export_limit_watts: int) -> bool:
        """Validates grid export limit in watts.

        Value 0 is intentionally rejected to avoid disabling export limit control.
        """
        return self.GRID_EXPORT_LIMIT_MIN_WATTS <= grid_export_limit_watts <= self.GRID_EXPORT_LIMIT_MAX_WATTS

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

        if setting_id == 'grid_export_limit':
            if not isinstance(value, int):
                log.error(
                    f'handle_set_message {self.serial_number} invalid grid_export_limit type: '
                    f'{payload_str!r}. Expected integer watts.'
                )
                return
            if not self.is_valid_grid_export_limit(value):
                log.error(
                    f'handle_set_message {self.serial_number} refusing invalid grid_export_limit '
                    f'(W): {value}. Allowed range: {self.GRID_EXPORT_LIMIT_MIN_WATTS}-'
                    f'{self.GRID_EXPORT_LIMIT_MAX_WATTS}'
                )
                return

        success = await self.write_setting(setting_id, value)
        if success:
            # Read back and publish the updated state
            try:
                current_value = await self.inverter.read_setting(setting_id)
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
            # battery_charge_current – number
            {
                "component": "number",
                "unique_id": f"{sn}_battery_charge_current",
                "name": "Battery Charge Current",
                "command_topic": f"{base}/set/battery_charge_current",
                "state_topic": f"{base}/state/battery_charge_current",
                "value_template": "{{ value_json.battery_charge_current }}",
                "unit_of_measurement": "A",
                "min": 0,
                "max": 25,
                "step": 1,
                "device": device,
            },
            # grid_export_limit – number
            {
                "component": "number",
                "unique_id": f"{sn}_grid_export_limit",
                "name": "Grid Export Limit",
                "command_topic": f"{base}/set/grid_export_limit",
                "state_topic": f"{base}/state/grid_export_limit",
                "value_template": "{{ value_json.grid_export_limit }}",
                "unit_of_measurement": "W",
                "min": self.GRID_EXPORT_LIMIT_MIN_WATTS,
                "max": self.GRID_EXPORT_LIMIT_MAX_WATTS,
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
            self.grid_export_limit = await self.inverter.get_grid_export_limit()
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
        if not self.is_valid_grid_export_limit(requested_grid_export_limit):
            log.error(
                f'set_grid_export_limit {self.serial_number} refusing invalid value '
                f'(W): {requested_grid_export_limit}. Allowed range: '
                f'{self.GRID_EXPORT_LIMIT_MIN_WATTS}-{self.GRID_EXPORT_LIMIT_MAX_WATTS}'
            )
            return
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
                        next_fast_runtime_data_time = now + self.mqtt_fast_runtime_data_interval_seconds
                        
                        log.debug(f'main_loop {self.serial_number} reading runtime data')
                        data = await self.read_runtime_data()
                        if data is None:
                            log.warning(f'main_loop {self.serial_number} Failed to read data. Retrying in 5s...')
                            await asyncio.sleep(5)
                            continue

                        # Publish fast runtime data
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

    # Gather tasks to keep main running
    tasks = [inv.mqtt_task for inv in inverters] + [inv.heartbeat_task_ref for inv in inverters]
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
