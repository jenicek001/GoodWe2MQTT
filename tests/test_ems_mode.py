"""Unit tests for EMS mode get/set via MQTT (control topic and /set/ topics)."""
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


def make_mqtt_client_with_message(payload: bytes) -> MagicMock:
    """Return a mock aiomqtt client that delivers one message then stops."""
    mock_message = MagicMock()
    mock_message.topic = MagicMock()
    mock_message.topic.__str__ = MagicMock(return_value="goodwe2mqtt/TEST_SN/control")
    mock_message.payload = payload

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()
    mock_client.messages = mock_messages
    return mock_client


# ---------------------------------------------------------------------------
# control topic – get_ems_mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_get_ems_mode():
    """`get_ems_mode` in payload should call the get_ems_mode helper."""
    gw = make_gw()
    mock_client = make_mqtt_client_with_message(b'{"get_ems_mode": 1}')

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get:
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_get.assert_awaited_once()


# ---------------------------------------------------------------------------
# control topic – set_ems_mode (valid, no limit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_set_ems_mode_valid():
    """`{"set_ems_mode": 8}` should call set_ems_mode(BATTERY_STANDBY, None)."""
    gw = make_gw()
    mock_client = make_mqtt_client_with_message(b'{"set_ems_mode": 8}')

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set:
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_set.assert_awaited_once_with(EMSMode.BATTERY_STANDBY, None)


# ---------------------------------------------------------------------------
# control topic – set_ems_mode (valid, with power limit)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_set_ems_mode_with_limit():
    """`{"set_ems_mode": 5, "ems_power_limit_watts": 3000}` passes limit correctly."""
    gw = make_gw()
    mock_client = make_mqtt_client_with_message(
        b'{"set_ems_mode": 5, "ems_power_limit_watts": 3000}'
    )

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set:
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_set.assert_awaited_once_with(EMSMode.EXPORT_AC, 3000)


# ---------------------------------------------------------------------------
# control topic – set_ems_mode (invalid value → error, no inverter call)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_set_ems_mode_invalid():
    """Out-of-range EMS mode value should log an error and NOT call set_ems_mode."""
    gw = make_gw()
    mock_client = make_mqtt_client_with_message(b'{"set_ems_mode": 999}')

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set:
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_set.assert_not_awaited()


# ---------------------------------------------------------------------------
# /set/ topic – ems_mode by name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_topic_ems_mode_by_name():
    """`/set/ems_mode` with payload `"BATTERY_STANDBY"` should write integer 8."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=8)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("ems_mode", "BATTERY_STANDBY")

    mock_write.assert_awaited_once_with("ems_mode", 8)


# ---------------------------------------------------------------------------
# /set/ topic – ems_mode by raw integer string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_topic_ems_mode_by_int():
    """`/set/ems_mode` with payload `"8"` (integer string) should write integer 8."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=8)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("ems_mode", "8")

    mock_write.assert_awaited_once_with("ems_mode", 8)


# ---------------------------------------------------------------------------
# /set/ topic – ems_power_limit_watts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_topic_ems_power_limit():
    """`/set/ems_power_limit_watts` with payload `"3000"` should write 3000 to ems_power_limit."""
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = AsyncMock(return_value=3000)

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write, \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock):
        await gw.handle_set_message("ems_power_limit_watts", "3000")

    mock_write.assert_awaited_once_with("ems_power_limit", 3000)


# ---------------------------------------------------------------------------
# publish_ha_discovery – EMS entities present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_ha_discovery_includes_ems_entities():
    """publish_ha_discovery should publish ems_mode select and ems_power_limit_watts number."""
    gw = make_gw()

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    topics = [c.args[0] for c in mock_pub.call_args_list]
    assert "homeassistant/select/TEST_SN_ems_mode/config" in topics
    assert "homeassistant/number/TEST_SN_ems_power_limit_watts/config" in topics
    assert mock_pub.await_count == 5
