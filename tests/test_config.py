from unittest.mock import patch
import pytest
import goodwe2mqtt

def test_read_config_success():
    """Test reading valid environment-based configuration."""
    with patch.dict("os.environ", {
        "G2M_MQTT_BROKER_IP": "127.0.0.1",
        "G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER": "SN123",
        "G2M_GOODWE_INVERTERS_0_IP_ADDRESS": "192.168.1.100",
    }, clear=False):
        config = goodwe2mqtt.read_config("dummy.yaml")
        assert config['mqtt']['broker_ip'] == "127.0.0.1"

def test_read_config_missing_inverters(mock_logger):
    """Test behavior when no inverters are configured."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(SystemExit):
            goodwe2mqtt.read_config("unused")

    mock_logger.log.error.assert_called()

def test_read_config_invalid_inverter_definition():
    """Test behavior when inverter env vars are incomplete."""
    with patch.dict("os.environ", {
        "G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER": "SN123",
    }, clear=True):
        with pytest.raises(SystemExit):
            goodwe2mqtt.read_config("unused")
