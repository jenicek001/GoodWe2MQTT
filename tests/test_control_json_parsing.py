"""Tests for /control message JSON parsing in mqtt_client_task.

These verify the get_*/set_* command dispatch in mqtt_client_task parses the
control payload as JSON up-front (via json.loads + dict key membership) rather
than doing a raw substring match on the message text.
"""
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import goodwe2mqtt
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


async def _run_with_messages(gw: goodwe2mqtt.Goodwe_MQTT, payloads: list) -> None:
    """Feed a sequence of control messages through mqtt_client_task."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()

    messages = []
    for payload in payloads:
        mock_message = MagicMock()
        mock_message.topic = MagicMock()
        mock_message.topic.__str__ = MagicMock(return_value=gw.mqtt_control_topic)
        mock_message.payload = payload
        messages.append(mock_message)

    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[*messages, StopAsyncIteration])
    mock_client.messages = mock_messages

    with patch("aiomqtt.Client", return_value=mock_client):
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_control_valid_json_dict_dispatches_command():
    """A well-formed JSON object should still dispatch to the matching handler."""
    gw = make_gw()

    with patch.object(gw, "get_operation_mode", new_callable=AsyncMock) as mock_get_om:
        await _run_with_messages(gw, [b'{"get_operation_mode": 1}'])

    mock_get_om.assert_awaited_once()


@pytest.mark.asyncio
async def test_control_invalid_json_payload_is_skipped_without_crashing():
    """Malformed JSON should be logged and skipped, not raise or crash the loop."""
    gw = make_gw()

    with patch.object(gw, "get_operation_mode", new_callable=AsyncMock) as mock_get_om:
        # First message is not valid JSON at all; second is a valid command.
        await _run_with_messages(gw, [b"not valid json {{{", b'{"get_operation_mode": 1}'])

    mock_get_om.assert_awaited_once()


@pytest.mark.asyncio
async def test_control_non_dict_json_payload_is_rejected():
    """Valid JSON that isn't an object (e.g. a bare number or array) should be rejected."""
    gw = make_gw()

    with patch.object(gw, "get_operation_mode", new_callable=AsyncMock) as mock_get_om, \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get_ems:
        await _run_with_messages(gw, [b"42", b"[1, 2, 3]", b'"get_operation_mode"'])

    mock_get_om.assert_not_awaited()
    mock_get_ems.assert_not_awaited()


@pytest.mark.asyncio
async def test_control_unknown_command_in_valid_json_logs_error_only():
    """An unrecognised but well-formed JSON command should hit the fallback 'else' branch."""
    gw = make_gw()

    with patch.object(gw, "get_operation_mode", new_callable=AsyncMock) as mock_get_om, \
         patch.object(gw, "get_ems_mode", new_callable=AsyncMock) as mock_get_ems, \
         patch.object(gw, "get_grid_export_limit", new_callable=AsyncMock) as mock_get_limit:
        await _run_with_messages(gw, [b'{"totally_unknown_command": 1}'])

    mock_get_om.assert_not_awaited()
    mock_get_ems.assert_not_awaited()
    mock_get_limit.assert_not_awaited()


@pytest.mark.asyncio
async def test_control_set_grid_export_limit_no_longer_double_parses_json():
    """set_grid_export_limit_watts should work correctly now that JSON is parsed once up-front."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    with patch.object(gw, "set_grid_export_limit", new_callable=AsyncMock) as mock_set, \
         patch.object(gw, "get_grid_export_limit", new_callable=AsyncMock, return_value=5000), \
         patch.object(gw, "send_mqtt_export_limit", new_callable=AsyncMock):
        await _run_with_messages(gw, [b'{"set_grid_export_limit_watts": 5000}'])

    mock_set.assert_awaited_once_with(5000)


@pytest.mark.asyncio
async def test_control_set_ems_mode_still_works_with_upfront_json_parsing():
    """set_ems_mode should still work correctly now that JSON is parsed once up-front."""
    gw = make_gw()
    gw.inverter = AsyncMock()

    from goodwe.inverter import EMSMode

    with patch.object(gw, "set_ems_mode", new_callable=AsyncMock) as mock_set_ems:
        await _run_with_messages(gw, [b'{"set_ems_mode": 8}'])

    mock_set_ems.assert_awaited_once_with(EMSMode.BATTERY_STANDBY, None)


@pytest.mark.asyncio
async def test_control_empty_payload_is_rejected():
    """An empty payload is not valid JSON and should be rejected without raising."""
    gw = make_gw()

    with patch.object(gw, "get_operation_mode", new_callable=AsyncMock) as mock_get_om:
        await _run_with_messages(gw, [b"", b'{"get_operation_mode": 1}'])

    mock_get_om.assert_awaited_once()
