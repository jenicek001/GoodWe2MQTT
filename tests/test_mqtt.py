import pytest
import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock
import goodwe2mqtt

@pytest.mark.asyncio
async def test_send_mqtt_response():
    """Test sending an MQTT response."""
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="user",
            mqtt_password="pass",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
    
    # Mock aiomqtt.Client
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock()
    mock_client.publish = AsyncMock()
    
    with patch("aiomqtt.Client", return_value=mock_client) as mock_client_init:
        await gw.send_mqtt_response("test/topic", {"key": "value"})
        
        mock_client_init.assert_called_once_with(
            "127.0.0.1", 1883, username="user", password="pass"
        )
        mock_client.publish.assert_called_once_with(
            "test/topic", payload=json.dumps({"key": "value"})
        )

@pytest.mark.asyncio
async def test_mqtt_client_task_subscription():
    """Test that mqtt_client_task subscribes to the correct topic."""
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="user",
            mqtt_password="pass",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
    
    mock_client = MagicMock()
    # First time return client, second time raise CancelledError to break loop
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()
    
    # Mock the messages provider
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
        assert gw.mqtt_control_topic == "test/TEST_SN/control"
        assert gw.mqtt_set_topic_wildcard == "test/TEST_SN/set/+"

@pytest.mark.asyncio
async def test_mqtt_client_task_process_message():
    """Test that mqtt_client_task processes an incoming message."""
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="user",
            mqtt_password="pass",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
    
    mock_client = MagicMock()
    # First time return client, second time raise CancelledError to break loop
    mock_client.__aenter__ = AsyncMock(side_effect=[mock_client, asyncio.CancelledError])
    mock_client.__aexit__ = AsyncMock()
    mock_client.subscribe = AsyncMock()
    
    # Mock a message
    mock_message = MagicMock()
    mock_message.payload = b'{"get_operation_mode": 1}'
    
    # Mock the messages provider iterator to return one message then stop
    mock_messages = MagicMock()
    mock_messages.__aiter__ = MagicMock(return_value=mock_messages)
    mock_messages.__anext__ = AsyncMock(side_effect=[mock_message, StopAsyncIteration])
    
    mock_client.messages = mock_messages
    
    with patch("aiomqtt.Client", return_value=mock_client), \
         patch.object(gw, 'get_operation_mode', new_callable=AsyncMock) as mock_get_om:
        
        try:
            await gw.mqtt_client_task()
        except asyncio.CancelledError:
            pass
        
        mock_get_om.assert_called_once()

