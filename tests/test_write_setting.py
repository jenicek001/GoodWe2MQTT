"""Tests for write_setting, handle_set_message, and publish_ha_discovery."""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import goodwe2mqtt


def make_gw() -> goodwe2mqtt.Goodwe_MQTT:
    """Create a Goodwe_MQTT instance with asyncio tasks suppressed."""
    with patch("asyncio.ensure_future"):
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
# write_setting
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_setting_success():
    """write_setting should call inverter.write_setting and return True."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    result = await gw.write_setting("grid_export_limit", 5000)

    assert result is True
    gw.inverter.write_setting.assert_awaited_once_with("grid_export_limit", 5000)


@pytest.mark.asyncio
async def test_write_setting_retry_then_success():
    """write_setting should retry on failure and succeed on the second attempt."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.write_setting.side_effect = [Exception("timeout"), None]

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await gw.write_setting("grid_export_limit", 3000, retries=3)

    assert result is True
    assert gw.inverter.write_setting.await_count == 2
    mock_sleep.assert_awaited_once_with(1)  # backoff for attempt 1


@pytest.mark.asyncio
async def test_write_setting_all_retries_exhausted():
    """write_setting should return False after all retries fail."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.write_setting.side_effect = Exception("timeout")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await gw.write_setting("grid_export_limit", 3000, retries=3)

    assert result is False
    assert gw.inverter.write_setting.await_count == 3


@pytest.mark.asyncio
async def test_write_setting_exponential_backoff():
    """write_setting should use exponential backoff (1s, 2s) between retries."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.write_setting.side_effect = Exception("timeout")

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await gw.write_setting("grid_export_limit", 0, retries=3)

    assert gw.inverter.write_setting.await_count == 3
    assert mock_sleep.await_count == 2
    mock_sleep.assert_any_await(1)
    mock_sleep.assert_any_await(2)


# ---------------------------------------------------------------------------
# handle_set_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_set_message_integer_payload():
    """handle_set_message should write an integer setting and publish state."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=5000)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("grid_export_limit", "5000")

    mock_write.assert_awaited_once_with("grid_export_limit", 5000)
    mock_pub.assert_awaited_once_with(
        "goodwe2mqtt/TEST_SN/state/grid_export_limit",
        {"grid_export_limit": 5000},
    )


@pytest.mark.asyncio
async def test_handle_set_message_work_mode_by_name():
    """handle_set_message should map work_mode string to integer before writing."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=4)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("work_mode", "Eco mode")

    mock_write.assert_awaited_once_with("work_mode", 4)


@pytest.mark.asyncio
async def test_handle_set_message_work_mode_by_integer():
    """handle_set_message should accept a numeric string for work_mode."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=0)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("work_mode", "0")

    mock_write.assert_awaited_once_with("work_mode", 0)


@pytest.mark.asyncio
async def test_handle_set_message_invalid_work_mode():
    """handle_set_message should log error and not call write_setting for bad work_mode."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("work_mode", "not_a_mode")

    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_set_message_write_failure_no_publish():
    """handle_set_message should NOT publish state when write_setting fails."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=False), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_set_message("battery_charge_current", "10")

    mock_pub.assert_not_awaited()


# ---------------------------------------------------------------------------
# mqtt_client_task – /set/ wildcard subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mqtt_client_task_subscribes_to_set_wildcard():
    """mqtt_client_task should subscribe to both control and set/+ topics."""
    gw = make_gw()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

    mock_client.messages = mock_messages

    with patch("aiomqtt.Client", return_value=mock_client):
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    subscribe_calls = [c.args[0] for c in mock_client.subscribe.call_args_list]
    assert gw.mqtt_control_topic in subscribe_calls
    assert gw.mqtt_set_topic_wildcard in subscribe_calls


@pytest.mark.asyncio
async def test_mqtt_client_task_routes_set_message():
    """mqtt_client_task should call handle_set_message for /set/ topics."""
    gw = make_gw()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    mock_message = MagicMock()
    mock_message.topic = MagicMock()
    mock_message.topic.__str__ = MagicMock(return_value="goodwe2mqtt/TEST_SN/set/grid_export_limit")
    mock_message.payload = b"5000"

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])

    mock_client.messages = mock_messages

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(gw, "handle_set_message", new_callable=AsyncMock) as mock_handle:
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_handle.assert_awaited_once_with("grid_export_limit", "5000")


# ---------------------------------------------------------------------------
# publish_ha_discovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_ha_discovery_publishes_three_entities():
    """publish_ha_discovery should publish configs for all three entities."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    assert mock_pub.await_count == 3
    topics = [c.args[0] for c in mock_pub.call_args_list]
    assert "homeassistant/select/TEST_SN_work_mode/config" in topics
    assert "homeassistant/number/TEST_SN_battery_charge_current/config" in topics
    assert "homeassistant/number/TEST_SN_grid_export_limit/config" in topics


@pytest.mark.asyncio
async def test_publish_ha_discovery_work_mode_options():
    """publish_ha_discovery work_mode config should include all mode options."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    work_mode_call = next(
        c for c in mock_pub.call_args_list
        if "select" in c.args[0]
    )
    payload = work_mode_call.args[1]
    assert payload["options"] == ["General mode", "Off grid mode", "Backup mode", "Eco mode"]
    assert payload["command_topic"] == "goodwe2mqtt/TEST_SN/set/work_mode"


@pytest.mark.asyncio
async def test_publish_ha_discovery_grid_export_limit_range():
    """publish_ha_discovery grid_export_limit should have correct min/max."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    gel_call = next(
        c for c in mock_pub.call_args_list
        if "grid_export_limit" in c.args[0] and "number" in c.args[0]
    )
    payload = gel_call.args[1]
    assert payload["min"] == 0
    assert payload["max"] == 10000
    assert payload["unit_of_measurement"] == "W"


@pytest.mark.asyncio
async def test_publish_ha_discovery_battery_charge_current_range():
    """publish_ha_discovery battery_charge_current should have correct min/max."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    bcc_call = next(
        c for c in mock_pub.call_args_list
        if "battery_charge_current" in c.args[0]
    )
    payload = bcc_call.args[1]
    assert payload["min"] == 0
    assert payload["max"] == 25
    assert payload["unit_of_measurement"] == "A"
