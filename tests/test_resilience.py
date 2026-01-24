import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from goodwe2mqtt import Goodwe_MQTT
import goodwe

@pytest.fixture
def mock_config():
    return {
        "goodwe": {
            "inverters": [
                {"serial_number": "123", "ip_address": "192.168.1.100"}
            ]
        },
        "mqtt": {
            "broker_ip": "192.168.1.10",
            "broker_port": 1883,
            "username": "user",
            "password": "password",
            "topic_prefix": "goodwe",
            "control_topic_postfix": "control",
            "runtime_data_topic_postfix": "runtime",
            "runtime_data_interval_seconds": 10,
            "fast_runtime_data_topic_postfix": "fast_runtime",
            "fast_runtime_data_interval_seconds": 1,
            "grid_export_limit_topic_postfix": "limit"
        }
    }

@pytest.mark.asyncio
async def test_connect_inverter_failure(mock_config):
    """Test that connect_inverter handles connection failure gracefully (should NOT raise exception)."""
    # Setup
    inv_config = mock_config["goodwe"]["inverters"][0]
    mqtt_config = mock_config["mqtt"]
    
    gw = Goodwe_MQTT(
        inv_config["serial_number"], inv_config["ip_address"],
        mqtt_config["broker_ip"], mqtt_config["broker_port"],
        mqtt_config["username"], mqtt_config["password"],
        mqtt_config["topic_prefix"], mqtt_config["control_topic_postfix"],
        mqtt_config["runtime_data_topic_postfix"], mqtt_config["runtime_data_interval_seconds"],
        mqtt_config["fast_runtime_data_topic_postfix"], mqtt_config["fast_runtime_data_interval_seconds"],
        mqtt_config["grid_export_limit_topic_postfix"]
    )

    # Mock goodwe.connect to raise a timeout
    with patch('goodwe.connect', side_effect=asyncio.TimeoutError("Connection timed out")):
        # We expect it to NOT raise an exception.
        # If it raises, the test fails (Red Phase).
        try:
            await gw.connect_inverter()
        except asyncio.TimeoutError:
            pytest.fail("connect_inverter raised TimeoutError instead of handling it gracefully")
        except Exception as e:
            pytest.fail(f"connect_inverter raised unexpected exception: {e}")


@pytest.mark.asyncio
async def test_mqtt_client_task_reconnect_bug(mock_config):
    """Test that mqtt_client_task handles connection failure by sleeping (retrying)."""
    # Setup
    inv_config = mock_config["goodwe"]["inverters"][0]
    mqtt_config = mock_config["mqtt"]
    
    gw = Goodwe_MQTT(
        inv_config["serial_number"], inv_config["ip_address"],
        mqtt_config["broker_ip"], mqtt_config["broker_port"],
        mqtt_config["username"], mqtt_config["password"],
        mqtt_config["topic_prefix"], mqtt_config["control_topic_postfix"],
        mqtt_config["runtime_data_topic_postfix"], mqtt_config["runtime_data_interval_seconds"],
        mqtt_config["fast_runtime_data_topic_postfix"], mqtt_config["fast_runtime_data_interval_seconds"],
        mqtt_config["grid_export_limit_topic_postfix"]
    )

    # Mock aiomqtt.Client to raise exception on connection
    mock_client = MagicMock()
    # When entering context manager, raise exception
    mock_client.__aenter__.side_effect = Exception("MQTT Connection Failed")
    
    with patch('aiomqtt.Client', return_value=mock_client):
        # We mock sleep to raise CancelledError to break the infinite loop
        with patch('asyncio.sleep', side_effect=asyncio.CancelledError) as mock_sleep:
             
             with pytest.raises(asyncio.CancelledError):
                 await gw.mqtt_client_task()
             
             # Assert that sleep was called (proving it hit the retry logic)
             mock_sleep.assert_called_with(5)

