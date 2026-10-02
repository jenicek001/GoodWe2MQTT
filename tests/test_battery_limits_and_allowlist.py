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
    ("battery_charge_current_limit_amps", "26"),
    ("battery_charge_current_amps", "-1"),
    ("battery_discharge_current_limit_amps", "26"),
    ("battery_discharge_current_limit_amps", "abc"),
    ("grid_export_limit_watts", "10001"),
    ("grid_export_limit_watts", "-5"),
    ("work_mode", "4"),       # PEAK_SHAVING in goodwe 0.4.10 - was mapped to "Eco mode" (#18)
    ("work_mode", "5"),
    ("work_mode", "7"),
    ("work_mode", "Peak shaving"),
])
async def test_set_rejects_out_of_range_values(setting_id, payload):
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message(setting_id, payload)

    mock_write.assert_not_awaited()


# ---------------------------------------------------------------------------
# battery_discharge_current_limit_amps
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_battery_discharge_current_writes_library_setting_and_publishes_state():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=5.0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("battery_discharge_current_limit_amps", "5")

    mock_write.assert_awaited_once_with("battery_discharge_current", 5)
    gw.inverter.read_setting.assert_awaited_once_with("battery_discharge_current")
    mock_pub.assert_awaited_once_with(
        "goodwe2mqtt/TEST_SN/state/battery_discharge_current_limit_amps",
        {"battery_discharge_current_limit_amps": 5.0},
    )


@pytest.mark.asyncio
async def test_set_battery_discharge_current_zero_is_allowed():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=0.0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("battery_discharge_current_limit_amps", "0")

    mock_write.assert_awaited_once_with("battery_discharge_current", 0)


@pytest.mark.asyncio
async def test_ha_discovery_includes_battery_discharge_current():
    gw = make_gw()
    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    payloads = {c.args[0]: c.args[1] for c in mock_pub.call_args_list}
    entity = payloads["homeassistant/number/TEST_SN_battery_discharge_current_limit_amps/config"]
    assert entity["command_topic"] == "goodwe2mqtt/TEST_SN/set/battery_discharge_current_limit_amps"
    assert entity["state_topic"] == "goodwe2mqtt/TEST_SN/state/battery_discharge_current_limit_amps"
    assert (entity["min"], entity["max"], entity["unit_of_measurement"]) == (0, 25, "A")


# ---------------------------------------------------------------------------
# get/<setting_id>
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("setting_id,library_id,value", [
    ("battery_charge_current_limit_amps", "battery_charge_current", 25.0),
    ("battery_discharge_current_limit_amps", "battery_discharge_current", 18.0),
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


# ---------------------------------------------------------------------------
# Names (a limit, not a measurement) and 0.1 A resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_charge_limit_canonical_name_writes_and_publishes_canonical_state():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=10.0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("battery_charge_current_limit_amps", "10")

    mock_write.assert_awaited_once_with("battery_charge_current", 10.0)
    mock_pub.assert_awaited_once_with(
        "goodwe2mqtt/TEST_SN/state/battery_charge_current_limit_amps",
        {"battery_charge_current_limit_amps": 10.0},
    )


@pytest.mark.asyncio
async def test_deprecated_charge_name_still_works_and_publishes_both_states():
    """battery_charge_current_amps predates the _limit names; existing clients keep working."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=10.0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("battery_charge_current_amps", "10")

    mock_write.assert_awaited_once_with("battery_charge_current", 10.0)
    published = {c.args[0]: c.args[1] for c in mock_pub.call_args_list}
    assert published == {
        "goodwe2mqtt/TEST_SN/state/battery_charge_current_limit_amps": {"battery_charge_current_limit_amps": 10.0},
        "goodwe2mqtt/TEST_SN/state/battery_charge_current_amps": {"battery_charge_current_amps": 10.0},
    }


@pytest.mark.asyncio
async def test_old_discharge_name_is_gone():
    """battery_discharge_current_amps was live for under an hour; it is not kept."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("battery_discharge_current_amps", "5")
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,expected", [("18.5", 18.5), ("0.3", 0.3), ("25", 25.0), ("7.26", 7.3), ("0", 0.0)])
async def test_current_limits_accept_tenths_of_an_amp(payload, expected):
    """The register holds tenths of an amp (inverter_2 was found at 18.5 A); a restore must be able
    to write such a value back. More precision is rounded to 0.1 A."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=expected)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("battery_discharge_current_limit_amps", payload)

    mock_write.assert_awaited_once_with("battery_discharge_current", expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["25.1", "-0.1", "nan", "inf"])
async def test_current_limits_reject_out_of_range_decimals(payload):
    gw = make_gw()
    gw.inverter = AsyncMock()
    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("battery_charge_current_limit_amps", payload)
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_ems_power_and_export_limits_stay_whole_watts():
    gw = make_gw()
    gw.inverter = AsyncMock()
    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("grid_export_limit_watts", "5000.5")
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_ha_entities_are_named_as_limits():
    gw = make_gw()
    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    payloads = {c.args[0]: c.args[1] for c in mock_pub.call_args_list}
    charge = payloads["homeassistant/number/TEST_SN_battery_charge_current_amps/config"]  # unique_id kept
    discharge = payloads["homeassistant/number/TEST_SN_battery_discharge_current_limit_amps/config"]
    assert charge["name"] == "Battery Charge Current Limit"
    assert discharge["name"] == "Battery Discharge Current Limit"
    assert charge["command_topic"] == "goodwe2mqtt/TEST_SN/set/battery_charge_current_limit_amps"
    assert charge["state_topic"] == "goodwe2mqtt/TEST_SN/state/battery_charge_current_limit_amps"
    assert charge["value_template"] == "{{ value_json.battery_charge_current_limit_amps }}"
    assert (charge["step"], discharge["step"]) == (0.1, 0.1)


# ---------------------------------------------------------------------------
# work_mode through the library (#18)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("payload,mode_name", [("General mode", "GENERAL"), ("0", "GENERAL"),
                                               ("Off grid mode", "OFF_GRID"), ("Backup mode", "BACKUP"),
                                               ("Eco mode", "ECO"), ("3", "ECO")])
async def test_work_mode_uses_the_library_mode_switch(payload, mode_name):
    from goodwe.inverter import OperationMode
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=OperationMode[mode_name].value)
    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("work_mode", payload)
    gw.inverter.set_operation_mode.assert_awaited_once_with(OperationMode[mode_name])
    gw.inverter.write_setting.assert_not_awaited()                # never the raw register
    mock_pub.assert_awaited_once_with("goodwe2mqtt/TEST_SN/state/work_mode",
                                      {"work_mode": OperationMode[mode_name].value})


@pytest.mark.asyncio
async def test_work_mode_switch_is_retried_and_failure_publishes_nothing():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.set_operation_mode.side_effect = Exception("timeout")
    with patch("asyncio.sleep", new_callable=AsyncMock), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("work_mode", "General mode")
    assert gw.inverter.set_operation_mode.await_count == 3
    mock_pub.assert_not_awaited()


@pytest.mark.asyncio
async def test_ha_work_mode_options_are_the_library_modes():
    gw = make_gw()
    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()
    payloads = {c.args[0]: c.args[1] for c in mock_pub.call_args_list}
    options = payloads["homeassistant/select/TEST_SN_work_mode/config"]["options"]
    assert options == ["General mode", "Off grid mode", "Backup mode", "Eco mode"]
    assert goodwe2mqtt.Goodwe_MQTT.WORK_MODE_OPTIONS["Eco mode"] == 3
