import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
import goodwe2mqtt

@pytest.mark.asyncio
async def test_connect_inverter():
    """Test connecting to the inverter."""
    # Mock the goodwe.connect function
    with patch("goodwe.connect", new_callable=AsyncMock) as mock_connect, \
         patch("asyncio.ensure_future"):
        mock_inverter = MagicMock()
        mock_connect.return_value = mock_inverter
        
        # Instantiate Goodwe_MQTT
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
        
        # Call connect_inverter
        result = await gw.connect_inverter()
        
        assert result == mock_inverter
        mock_connect.assert_called_once_with(host="1.2.3.4", family='ET')

@pytest.mark.asyncio
async def test_read_runtime_data_success():
    """Test successful reading of runtime data."""
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
    
    mock_inverter = AsyncMock()
    gw.inverter = mock_inverter
    
    mock_data = {
        'timestamp': datetime(2023, 1, 1, 12, 0, 0),
        'ppv': 5000
    }
    mock_inverter.read_runtime_data.return_value = mock_data
    
    await gw.read_runtime_data()
    
    assert gw.runtime_data['ppv'] == 5000
    assert gw.runtime_data['timestamp'] == '2023-01-01T12:00:00'
    assert gw.runtime_data['serial_number'] == "TEST_SN"

@pytest.mark.asyncio
async def test_read_runtime_data_failure():
    """Test failure when reading runtime data."""
    import goodwe.exceptions
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
    
    mock_inverter = AsyncMock()
    gw.inverter = mock_inverter
    
    mock_inverter.read_runtime_data.side_effect = goodwe.exceptions.MaxRetriesException("Max retries")
    
    result = await gw.read_runtime_data()
    
    assert result is None
    assert gw.runtime_data is None

@pytest.mark.asyncio
async def test_get_operation_mode():

    """Test getting operation mode."""
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )
    
    mock_inverter = AsyncMock()
    gw.inverter = mock_inverter
    mock_inverter.get_operation_mode.return_value = 1 # e.g., General mode
    
    # We also need to mock send_mqtt_response because get_operation_mode calls it
    with patch.object(gw, 'send_mqtt_response', new_callable=AsyncMock) as mock_send:
        result = await gw.get_operation_mode()
        assert result == 1
        assert gw.operation_mode == 1
        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_set_grid_export_limit_rejects_zero():
    """set_grid_export_limit should reject 0 to avoid disabling limit control."""
    with patch("asyncio.ensure_future"):
        gw = goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_topic_prefix="test",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit"
        )

    gw.inverter = AsyncMock()
    await gw.set_grid_export_limit(0)

    gw.inverter.set_grid_export_limit.assert_not_awaited()

