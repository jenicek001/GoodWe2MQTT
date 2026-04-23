"""Unit tests for SEC1000S_MQTT class — safety logic, MQTT dispatch, verify loop."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import goodwe2mqtt
from conftest import suppress_ensure_future


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_sec(**kwargs) -> goodwe2mqtt.SEC1000S_MQTT:
    """Create a SEC1000S_MQTT instance with asyncio tasks suppressed."""
    defaults = dict(
        name="test_sec",
        host="192.168.1.100",
        port=1234,
        timeout=10.0,
        min_limit_w=100,
        contractual_limit_w=10000,
        contractual_safety_margin=0.10,
        scan_three_phases=False,
        telemetry_interval_seconds=5,
        grid_export_limit_interval_seconds=30,
        set_verify_retries=3,
        set_verify_delay_seconds=2.0,
        mqtt_broker_ip="127.0.0.1",
        mqtt_broker_port=1883,
        mqtt_username=None,
        mqtt_password=None,
        mqtt_topic_prefix="goodwe2mqtt",
    )
    defaults.update(kwargs)
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
        return goodwe2mqtt.SEC1000S_MQTT(**defaults)


_EXPORT_LIMIT_RESPONSE = {
    "control_mode": 3,
    "total_capacity_watts": 10000,
    "grid_export_limit_watts": 3000,
}


# ---------------------------------------------------------------------------
# __init__ — topic construction
# ---------------------------------------------------------------------------

def test_init_effective_ceiling():
    """effective_ceiling_w = contractual × (1 - margin)."""
    sec = make_sec(contractual_limit_w=10000, contractual_safety_margin=0.10)
    assert sec.effective_ceiling_w == 9000


def test_init_topic_structure():
    """MQTT topics should follow goodwe2mqtt/sec1000s/<name>/ pattern."""
    sec = make_sec(name="home", mqtt_topic_prefix="goodwe2mqtt")
    assert sec.telemetry_topic == "goodwe2mqtt/sec1000s/home/telemetry"
    assert sec.grid_export_limit_topic == "goodwe2mqtt/sec1000s/home/grid_export_limit"
    assert sec.status_topic == "goodwe2mqtt/sec1000s/home/status"
    assert sec.control_topic == "goodwe2mqtt/sec1000s/home/control"


# ---------------------------------------------------------------------------
# set_grid_export_limit_with_verify — safety floor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_floor_rejects_and_publishes_error():
    """Limits below min_limit_w must be rejected without touching the device."""
    sec = make_sec(min_limit_w=100)

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock) as mock_get, \
         patch("sec1000s_protocol.set_grid_export_limit", new_callable=AsyncMock) as mock_set, \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock) as mock_enable, \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await sec.set_grid_export_limit_with_verify(50)

    mock_get.assert_not_awaited()
    mock_set.assert_not_awaited()
    mock_enable.assert_not_awaited()

    mock_pub.assert_awaited_once()
    topic, payload = mock_pub.call_args[0]
    assert topic == sec.grid_export_limit_topic
    assert "error" in payload


@pytest.mark.asyncio
async def test_safety_floor_exact_boundary_rejects():
    """A limit exactly equal to min_limit_w - 1 must also be rejected."""
    sec = make_sec(min_limit_w=100)

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock), \
         patch("sec1000s_protocol.set_grid_export_limit", new_callable=AsyncMock) as mock_set, \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock), \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(99)

    mock_set.assert_not_awaited()


# ---------------------------------------------------------------------------
# set_grid_export_limit_with_verify — contractual ceiling clamping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contractual_ceiling_clamps_silently():
    """A request above effective_ceiling_w should be silently clamped to ceiling."""
    sec = make_sec(contractual_limit_w=10000, contractual_safety_margin=0.10)
    # effective_ceiling_w = 9000

    sent_limit = None

    async def capture_set(host, port, timeout, limit_watts, total_capacity_watts, scan_three_phases):
        nonlocal sent_limit
        sent_limit = limit_watts
        return True

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock, side_effect=[
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 9000, "control_mode": 3},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 9000, "control_mode": 3},
    ]), \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock, return_value=True), \
         patch("sec1000s_protocol.set_grid_export_limit", side_effect=capture_set), \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(15000)

    assert sent_limit == 9000


@pytest.mark.asyncio
async def test_exact_ceiling_passes():
    """A request equal to effective_ceiling_w should not be clamped."""
    sec = make_sec(contractual_limit_w=10000, contractual_safety_margin=0.10)
    # effective_ceiling_w = 9000

    sent_limit = None

    async def capture_set(host, port, timeout, limit_watts, total_capacity_watts, scan_three_phases):
        nonlocal sent_limit
        sent_limit = limit_watts
        return True

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock, side_effect=[
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 9000, "control_mode": 3},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 9000, "control_mode": 3},
    ]), \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock, return_value=True), \
         patch("sec1000s_protocol.set_grid_export_limit", side_effect=capture_set), \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(9000)

    assert sent_limit == 9000


# ---------------------------------------------------------------------------
# set_grid_export_limit_with_verify — successful verify path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_export_limit_with_verify_success():
    """Successful path: set, readback confirms, publish grid_export_limit state."""
    sec = make_sec()

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock, side_effect=[
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 0, "control_mode": 0},  # get total_cap
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 3000, "control_mode": 3},  # readback
    ]), \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock, return_value=True), \
         patch("sec1000s_protocol.set_grid_export_limit", new_callable=AsyncMock, return_value=True), \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(3000)

    mock_pub.assert_awaited_once()
    topic, payload = mock_pub.call_args[0]
    assert topic == sec.grid_export_limit_topic
    assert payload["grid_export_limit_watts"] == 3000
    assert payload["effective_ceiling_watts"] == sec.effective_ceiling_w
    assert "last_seen" in payload
    assert "error" not in payload


@pytest.mark.asyncio
async def test_set_export_limit_within_tolerance():
    """Readback within 50 W of requested value should count as success."""
    sec = make_sec()

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock, side_effect=[
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 0, "control_mode": 0},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 2975, "control_mode": 3},  # 25 W off
    ]), \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock, return_value=True), \
         patch("sec1000s_protocol.set_grid_export_limit", new_callable=AsyncMock, return_value=True), \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(3000)

    mock_pub.assert_awaited_once()
    payload = mock_pub.call_args[0][1]
    assert "error" not in payload


# ---------------------------------------------------------------------------
# set_grid_export_limit_with_verify — retry and all-fail paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_export_limit_retries_on_mismatch():
    """On readback mismatch, should retry up to set_verify_retries times."""
    sec = make_sec(set_verify_retries=2)

    # get_grid_export_limit calls: 2× (get total_cap + readback mismatch) = 4 calls
    get_side_effects = [
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 0, "control_mode": 0},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 999, "control_mode": 3},  # mismatch
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 0, "control_mode": 0},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 3000, "control_mode": 3},  # success
    ]

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock, side_effect=get_side_effects), \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock, return_value=True), \
         patch("sec1000s_protocol.set_grid_export_limit", new_callable=AsyncMock, return_value=True) as mock_set, \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(3000)

    assert mock_set.await_count == 2
    payload = mock_pub.call_args[0][1]
    assert "error" not in payload


@pytest.mark.asyncio
async def test_set_export_limit_all_retries_fail_publishes_error():
    """When all retries fail, should publish an error payload."""
    sec = make_sec(set_verify_retries=2)

    # Always mismatches on readback
    get_side_effects = [
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 0, "control_mode": 0},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 999, "control_mode": 3},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 0, "control_mode": 0},
        {"total_capacity_watts": 10000, "grid_export_limit_watts": 999, "control_mode": 3},
    ]

    with patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock, side_effect=get_side_effects), \
         patch("sec1000s_protocol.enable_value_mode", new_callable=AsyncMock, return_value=True), \
         patch("sec1000s_protocol.set_grid_export_limit", new_callable=AsyncMock, return_value=True), \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        await sec.set_grid_export_limit_with_verify(3000)

    mock_pub.assert_awaited_once()
    payload = mock_pub.call_args[0][1]
    assert "error" in payload


# ---------------------------------------------------------------------------
# mqtt_client_task — MQTT command dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_control_message_dispatches_set_export_limit_watts():
    """mqtt_client_task should call set_grid_export_limit_with_verify for set_grid_export_limit_watts."""
    sec = make_sec()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    mock_message = MagicMock()
    mock_message.topic = MagicMock()
    mock_message.topic.__str__ = MagicMock(return_value=sec.control_topic)
    mock_message.payload = b'{"set_grid_export_limit_watts": 3000}'

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])
    mock_client.messages = mock_messages

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(sec, "set_grid_export_limit_with_verify", new_callable=AsyncMock) as mock_set:
        try:
            await sec.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_set.assert_awaited_once_with(3000)


@pytest.mark.asyncio
async def test_control_message_dispatches_get_export_limit():
    """mqtt_client_task should call get_grid_export_limit and publish for get_grid_export_limit command."""
    sec = make_sec()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    mock_message = MagicMock()
    mock_message.topic = MagicMock()
    mock_message.topic.__str__ = MagicMock(return_value=sec.control_topic)
    mock_message.payload = b'{"get_grid_export_limit": 1}'

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])
    mock_client.messages = mock_messages

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch("sec1000s_protocol.get_grid_export_limit", new_callable=AsyncMock,
               return_value={**_EXPORT_LIMIT_RESPONSE}) as mock_get, \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        try:
            await sec.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    assert mock_get.await_count == 2  # once at startup, once for the command
    mock_pub.assert_awaited_once()
    topic, payload = mock_pub.call_args[0]
    assert topic == sec.grid_export_limit_topic
    assert "effective_ceiling_watts" in payload


@pytest.mark.asyncio
async def test_control_message_dispatches_get_telemetry():
    """mqtt_client_task should call get_telemetry and publish for get_telemetry command."""
    sec = make_sec()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    mock_message = MagicMock()
    mock_message.topic = MagicMock()
    mock_message.topic.__str__ = MagicMock(return_value=sec.control_topic)
    mock_message.payload = b'{"get_telemetry": 1}'

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])
    mock_client.messages = mock_messages

    telemetry_data = {
        "v1": 230.0, "v2": 230.0, "v3": 230.0,
        "i1": 5.0, "i2": 5.0, "i3": 5.0,
        "p1_watts": 1150, "p2_watts": 1150, "p3_watts": 1150,
        "meters_power_watts": 500, "inverters_power_watts": 4000,
        "load_power_watts": 3500,
    }

    with patch("aiomqtt.Client", return_value=mock_client), \
         patch("sec1000s_protocol.get_telemetry", new_callable=AsyncMock,
               return_value={**telemetry_data}) as mock_get, \
         patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        try:
            await sec.mqtt_client_task()
        except asyncio.CancelledError:
            pass

    mock_get.assert_awaited_once()
    mock_pub.assert_awaited_once()
    topic, payload = mock_pub.call_args[0]
    assert topic == sec.telemetry_topic
    assert "last_seen" in payload


# ---------------------------------------------------------------------------
# publish_ha_discovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_ha_discovery_structure():
    """publish_ha_discovery should publish to correct HA discovery topic."""
    sec = make_sec(name="home")

    with patch.object(sec, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await sec.publish_ha_discovery()

    mock_pub.assert_awaited_once()
    topic, payload = mock_pub.call_args[0]
    assert topic == "homeassistant/number/sec1000s_home_grid_export_limit_watts/config"
    assert payload["unit_of_measurement"] == "W"
    assert payload["min"] == sec.min_limit_w
    assert payload["max"] == sec.effective_ceiling_w
    assert payload["state_topic"] == "goodwe2mqtt/sec1000s/home/grid_export_limit"
    assert payload["value_template"] == "{{ value_json.grid_export_limit_watts }}"
