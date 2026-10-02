"""Tests for the /set/ allowlist, the battery discharge current setting, the get/ topics
and EMS power limit 0."""
import asyncio  # noqa: I001 - goodwe2mqtt before conftest, as in the other test modules
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import goodwe2mqtt
from goodwe.inverter import EMSMode
from conftest import suppress_ensure_future


def make_gw() -> goodwe2mqtt.Goodwe_MQTT:
    """Create a Goodwe_MQTT instance with asyncio tasks suppressed."""
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
        return goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="user",
            mqtt_password="pass",
            mqtt_topic_prefix="goodwe2mqtt",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="runtime_data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast_runtime_data",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="grid_export_limit",
        )


# ---------------------------------------------------------------------------
# /set/ allowlist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("setting_id", [
    "modbus47000",            # the goodwe library writes any raw register by this name
    "battery_charge_voltage",  # a real library setting, but not one this bridge exposes
    "shadow_scan",
    "",
])
async def test_set_rejects_settings_outside_allowlist(setting_id):
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message(setting_id, "1")

    mock_write.assert_not_awaited()
    gw.inverter.write_setting.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("setting_id,payload", [
    ("battery_charge_current_amps", "26"),
    ("battery_charge_current_amps", "-1"),
    ("battery_discharge_current_amps", "26"),
    ("battery_discharge_current_amps", "abc"),
    ("grid_export_limit_watts", "10001"),
    ("grid_export_limit_watts", "-5"),
    ("work_mode", "3"),       # not a known work mode
    ("work_mode", "7"),
])
async def test_set_rejects_out_of_range_values(setting_id, payload):
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message(setting_id, payload)

    mock_write.assert_not_awaited()


# ---------------------------------------------------------------------------
# battery_discharge_current_amps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_battery_discharge_current_writes_library_setting_and_publishes_state():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=5.0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("battery_discharge_current_amps", "5")

    mock_write.assert_awaited_once_with("battery_discharge_current", 5)
    gw.inverter.read_setting.assert_awaited_once_with("battery_discharge_current")
    mock_pub.assert_awaited_once_with(
        "goodwe2mqtt/TEST_SN/state/battery_discharge_current_amps",
        {"battery_discharge_current_amps": 5.0},
    )


@pytest.mark.asyncio
async def test_set_battery_discharge_current_zero_is_allowed():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=0.0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("battery_discharge_current_amps", "0")

    mock_write.assert_awaited_once_with("battery_discharge_current", 0)


@pytest.mark.asyncio
async def test_ha_discovery_includes_battery_discharge_current():
    gw = make_gw()
    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    payloads = {c.args[0]: c.args[1] for c in mock_pub.call_args_list}
    entity = payloads["homeassistant/number/TEST_SN_battery_discharge_current_amps/config"]
    assert entity["command_topic"] == "goodwe2mqtt/TEST_SN/set/battery_discharge_current_amps"
    assert entity["state_topic"] == "goodwe2mqtt/TEST_SN/state/battery_discharge_current_amps"
    assert (entity["min"], entity["max"], entity["unit_of_measurement"]) == (0, 25, "A")


# ---------------------------------------------------------------------------
# get/<setting_id>
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("setting_id,library_id,value", [
    ("battery_charge_current_amps", "battery_charge_current", 25.0),
    ("battery_discharge_current_amps", "battery_discharge_current", 18.0),
    ("grid_export_limit_watts", "grid_export_limit", 10000),
    ("work_mode", "work_mode", 0),
])
async def test_get_reads_setting_and_publishes_state(setting_id, library_id, value):
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=value)

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_get_message(setting_id)

    gw.inverter.read_setting.assert_awaited_once_with(library_id)
    mock_pub.assert_awaited_once_with(f"goodwe2mqtt/TEST_SN/state/{setting_id}", {setting_id: value})
    gw.inverter.write_setting.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("setting_id", ["ems_mode", "ems_power_limit_watts"])
async def test_get_ems_settings_publish_the_combined_ems_state(setting_id):
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get:
        await gw.handle_get_message(setting_id)

    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_rejects_settings_outside_allowlist():
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_get_message("modbus47000")

    gw.inverter.read_setting.assert_not_awaited()
    mock_pub.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_read_failure_publishes_nothing():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(side_effect=Exception("timeout"))

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_get_message("battery_charge_current_amps")

    mock_pub.assert_not_awaited()


def _client_with_messages(messages):
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()
    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[*messages, StopAsyncIteration])
    mock_client.messages = mock_messages
    return mock_client


@pytest.mark.asyncio
async def test_mqtt_client_task_subscribes_to_get_wildcard_and_routes_get():
    gw = make_gw()
    message = MagicMock()
    message.topic = MagicMock()
    message.topic.__str__ = MagicMock(return_value="goodwe2mqtt/TEST_SN/get/battery_charge_current_amps")
    message.payload = b""
    client = _client_with_messages([message])

    with patch("aiomqtt.Client", return_value=client), \
         patch.object(gw, "handle_get_message", new_callable=AsyncMock) as mock_handle:
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    assert "goodwe2mqtt/TEST_SN/get/+" in [c.args[0] for c in client.subscribe.call_args_list]
    mock_handle.assert_awaited_once_with("battery_charge_current_amps")


# ---------------------------------------------------------------------------
# EMS power limit 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_ems_mode_with_power_limit_zero_writes_the_zero():
    """goodwe 0.4.10 skips the power limit write when it is 0 (`if ems_power_limit:`), which
    would leave the previous setpoint in force. The bridge writes the 0 itself."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "get_ems_mode", new_callable=AsyncMock):
        await gw.set_ems_mode(EMSMode.AUTO, 0)

    gw.inverter.set_ems_mode.assert_awaited_once_with(EMSMode.AUTO, 0)
    gw.inverter.write_setting.assert_awaited_once_with("ems_power_limit", 0)


@pytest.mark.asyncio
async def test_set_ems_mode_without_power_limit_leaves_it_alone():
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "get_ems_mode", new_callable=AsyncMock):
        await gw.set_ems_mode(EMSMode.BATTERY_STANDBY, None)

    gw.inverter.write_setting.assert_not_awaited()
