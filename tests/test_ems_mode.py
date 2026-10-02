"""Tests for EMS mode support: get_ems_mode, set_ems_mode, /control commands,
/set/ topic handling, and Home Assistant discovery entities."""
import asyncio
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
# get_ems_mode / set_ems_mode helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_ems_mode_success():
    """get_ems_mode should publish mode + power limit to the ems_mode topic."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.get_ems_mode.return_value = EMSMode.BATTERY_STANDBY
    gw.inverter.read_setting.return_value = 0

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.get_ems_mode()

    gw.inverter.read_setting.assert_awaited_once_with("ems_power_limit")
    mock_pub.assert_awaited_once()
    topic, payload = mock_pub.call_args.args
    assert topic == "goodwe2mqtt/TEST_SN/ems_mode"
    assert payload["ems_mode"] == 8
    assert payload["ems_mode_name"] == "BATTERY_STANDBY"
    assert payload["ems_power_limit_watts"] == 0
    assert payload["serial_number"] == "TEST_SN"


@pytest.mark.asyncio
async def test_get_ems_mode_unknown_mode():
    """get_ems_mode should publish None fields when the inverter returns an unknown mode."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.get_ems_mode.return_value = None
    gw.inverter.read_setting.return_value = None

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.get_ems_mode()

    payload = mock_pub.call_args.args[1]
    assert payload["ems_mode"] is None
    assert payload["ems_mode_name"] is None


@pytest.mark.asyncio
async def test_get_ems_mode_failure_does_not_raise():
    """get_ems_mode should swallow exceptions and not publish."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.get_ems_mode.side_effect = Exception("comm error")

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.get_ems_mode()

    mock_pub.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_ems_mode_calls_library_and_republishes():
    """set_ems_mode should call inverter.set_ems_mode then re-read via get_ems_mode."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get:
        await gw.set_ems_mode(EMSMode.DISCHARGE_BATTERY, 3000)

    gw.inverter.set_ems_mode.assert_awaited_once_with(EMSMode.DISCHARGE_BATTERY, 3000)
    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_ems_mode_failure_does_not_republish():
    """set_ems_mode should not call get_ems_mode if the inverter write fails."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.set_ems_mode.side_effect = Exception("comm error")

    with patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get:
        await gw.set_ems_mode(EMSMode.AUTO)

    mock_get.assert_not_awaited()


# ---------------------------------------------------------------------------
# /control command handling
# ---------------------------------------------------------------------------

async def _run_with_message(gw: goodwe2mqtt.Goodwe_MQTT, payload: bytes) -> None:
    """Feed a single control message through mqtt_client_task."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    mock_message = MagicMock()
    mock_message.topic = MagicMock()
    mock_message.topic.__str__ = MagicMock(return_value=gw.mqtt_control_topic)
    mock_message.payload = payload

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])
    mock_client.messages = mock_messages

    with patch("aiomqtt.Client", return_value=mock_client):
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_control_get_ems_mode():
    """Control payload {'get_ems_mode': 1} should call get_ems_mode."""
    gw = make_gw()

    with patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get_ems:
        await _run_with_message(gw, b'{"get_ems_mode": 1}')

    mock_get_ems.assert_awaited_once()


@pytest.mark.asyncio
async def test_control_set_ems_mode_valid():
    """Control payload {'set_ems_mode': 8} should call set_ems_mode(BATTERY_STANDBY, None)."""
    gw = make_gw()

    with patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set_ems:
        await _run_with_message(gw, b'{"set_ems_mode": 8}')

    mock_set_ems.assert_awaited_once_with(EMSMode.BATTERY_STANDBY, None)


@pytest.mark.asyncio
async def test_control_set_ems_mode_with_limit():
    """Control payload with ems_power_limit_watts should pass the limit through."""
    gw = make_gw()

    with patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set_ems:
        await _run_with_message(gw, b'{"set_ems_mode": 12, "ems_power_limit_watts": 3000}')

    mock_set_ems.assert_awaited_once_with(EMSMode.DISCHARGE_BATTERY, 3000)


@pytest.mark.asyncio
async def test_control_set_ems_mode_invalid_mode_value():
    """An out-of-range EMS mode integer should be rejected without calling set_ems_mode."""
    gw = make_gw()

    with patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set_ems:
        await _run_with_message(gw, b'{"set_ems_mode": 99}')

    mock_set_ems.assert_not_awaited()


@pytest.mark.asyncio
async def test_control_set_ems_mode_out_of_range_power_limit():
    """An out-of-range ems_power_limit_watts should be rejected without calling set_ems_mode."""
    gw = make_gw()

    with patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set_ems:
        await _run_with_message(gw, b'{"set_ems_mode": 10, "ems_power_limit_watts": 999999}')

    mock_set_ems.assert_not_awaited()


# ---------------------------------------------------------------------------
# handle_set_message – ems_mode / ems_power_limit_watts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_set_message_ems_mode_by_name():
    """/set/ems_mode with a mode name should resolve to the integer value."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get_ems:
        await gw.handle_set_message("ems_mode", "BATTERY_STANDBY")

    mock_write.assert_awaited_once_with("ems_mode", 8)
    mock_get_ems.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_set_message_ems_mode_by_integer():
    """/set/ems_mode with a raw integer string should be accepted."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock):
        await gw.handle_set_message("ems_mode", "8")

    mock_write.assert_awaited_once_with("ems_mode", 8)


@pytest.mark.asyncio
async def test_handle_set_message_ems_mode_invalid():
    """/set/ems_mode with an invalid value should not write to the inverter."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("ems_mode", "99")

    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_set_message_ems_power_limit_watts():
    """/set/ems_power_limit_watts should write the raw register and republish combined state."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get_ems:
        await gw.handle_set_message("ems_power_limit_watts", "3000")

    mock_write.assert_awaited_once_with("ems_power_limit", 3000)
    mock_get_ems.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_set_message_ems_power_limit_watts_out_of_range():
    """/set/ems_power_limit_watts outside the valid range should not be written."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("ems_power_limit_watts", "999999")

    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_set_message_ems_mode_write_failure_no_republish():
    """handle_set_message should not call get_ems_mode when write_setting fails."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=False), \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get_ems:
        await gw.handle_set_message("ems_mode", "8")

    mock_get_ems.assert_not_awaited()


# ---------------------------------------------------------------------------
# publish_ha_discovery – EMS entities
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_ha_discovery_includes_ems_entities():
    """publish_ha_discovery should publish six entities including the EMS ones."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    assert mock_pub.await_count == 6
    topics = [c.args[0] for c in mock_pub.call_args_list]
    assert "homeassistant/select/TEST_SN_ems_mode/config" in topics
    assert "homeassistant/number/TEST_SN_ems_power_limit_watts/config" in topics


@pytest.mark.asyncio
async def test_publish_ha_discovery_ems_mode_select_options():
    """The EMS mode select entity should list all EMSMode names and use the combined state topic."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    ems_call = next(
        c for c in mock_pub.call_args_list
        if c.args[0] == "homeassistant/select/TEST_SN_ems_mode/config"
    )
    payload = ems_call.args[1]
    assert payload["options"] == [m.name for m in EMSMode]
    assert payload["command_topic"] == "goodwe2mqtt/TEST_SN/set/ems_mode"
    assert payload["state_topic"] == "goodwe2mqtt/TEST_SN/ems_mode"
    assert payload["value_template"] == "{{ value_json.ems_mode_name }}"


@pytest.mark.asyncio
async def test_publish_ha_discovery_ems_power_limit_number():
    """The EMS power limit number entity should share the combined ems_mode state topic."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    limit_call = next(
        c for c in mock_pub.call_args_list
        if c.args[0] == "homeassistant/number/TEST_SN_ems_power_limit_watts/config"
    )
    payload = limit_call.args[1]
    assert payload["state_topic"] == "goodwe2mqtt/TEST_SN/ems_mode"
    assert payload["command_topic"] == "goodwe2mqtt/TEST_SN/set/ems_power_limit_watts"
    assert payload["min"] == 0
    assert payload["max"] == 15000
    assert payload["unit_of_measurement"] == "W"
