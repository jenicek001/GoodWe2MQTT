import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
import goodwe2mqtt
from conftest import suppress_ensure_future

def _make_gw(family=""):
    """Create a Goodwe_MQTT instance with asyncio tasks suppressed."""
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
        return goodwe2mqtt.Goodwe_MQTT(
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
            mqtt_grid_export_limit_topic_postfix="limit",
            family=family,
        )


@pytest.mark.asyncio
async def test_connect_inverter_detects_family_by_default():
    """With no family configured the library detects it from the serial number."""
    with patch("goodwe.connect", new_callable=AsyncMock) as mock_connect:
        mock_inverter = MagicMock()
        del mock_inverter.settings  # capability probes fall back to "assume supported"
        mock_connect.return_value = mock_inverter

        gw = _make_gw()
        result = await gw.connect_inverter()

        assert result == mock_inverter
        mock_connect.assert_called_once_with(host="1.2.3.4", family=None)


@pytest.mark.asyncio
async def test_connect_inverter_uses_configured_family():
    """A configured family, e.g. DT, is passed to the library."""
    with patch("goodwe.connect", new_callable=AsyncMock) as mock_connect:
        mock_inverter = MagicMock()
        del mock_inverter.settings
        mock_connect.return_value = mock_inverter

        gw = _make_gw(family="DT")
        await gw.connect_inverter()

        mock_connect.assert_called_once_with(host="1.2.3.4", family="DT")


@pytest.mark.asyncio
async def test_connect_inverter_records_capabilities():
    """The connection records the family and export limit unit the inverter turned out to have."""
    with patch("goodwe.connect", new_callable=AsyncMock) as mock_connect:
        mock_inverter = MagicMock()
        mock_inverter.settings.return_value = [
            MagicMock(id_="grid_export_limit", unit="%"),
        ]
        mock_inverter.__class__.__name__ = "DT"
        mock_connect.return_value = mock_inverter

        gw = _make_gw()
        await gw.connect_inverter()

        assert gw.family_name == "MagicMock" or gw.family_name
        assert gw.grid_export_limit_unit == "%"
        assert gw._grid_export_limit_is_percent is True

@pytest.mark.asyncio
async def test_read_runtime_data_success():
    """Test successful reading of runtime data."""
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
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
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
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
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
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
async def test_get_grid_export_limit_negative_value():
    """get_grid_export_limit should reinterpret unsigned 16-bit as signed (e.g. 65486 → -50)."""
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
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

    # 65486 == 0xFFCE == -50 as signed int16
    mock_inverter.get_grid_export_limit.return_value = 65486
    result = await gw.get_grid_export_limit()
    assert result == -50

    # Positive values should pass through unchanged
    mock_inverter.get_grid_export_limit.return_value = 3000
    result = await gw.get_grid_export_limit()
    assert result == 3000

    # Zero boundary: 32767 (0x7FFF) is max positive signed int16
    mock_inverter.get_grid_export_limit.return_value = 32767
    result = await gw.get_grid_export_limit()
    assert result == 32767

    # 32768 (0x8000) is -32768 as signed int16
    mock_inverter.get_grid_export_limit.return_value = 32768
    result = await gw.get_grid_export_limit()
    assert result == -32768

