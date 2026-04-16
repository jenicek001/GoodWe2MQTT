import os
from unittest.mock import patch
import goodwe2mqtt

def test_read_config_env_override():
    """Test that environment variables override default configuration."""
    with patch.dict(os.environ, {
        "G2M_MQTT_BROKER_IP": "10.0.0.1",
        "G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER": "SN123",
        "G2M_GOODWE_INVERTERS_0_IP_ADDRESS": "192.168.1.100",
    }, clear=False):
        config = goodwe2mqtt.read_config("dummy.yaml")
        assert config["mqtt"]["broker_ip"] == "10.0.0.1"

def test_read_config_env_nested_override():
    """Test overriding nested and list values via environment variables."""
    with patch.dict(os.environ, {
        "G2M_MQTT_BROKER_PORT": "8883",
        "G2M_GOODWE_INVERTERS_0_SERIAL_NUMBER": "SN123",
        "G2M_GOODWE_INVERTERS_0_IP_ADDRESS": "192.168.1.100",
        "G2M_GOODWE_INVERTERS_1_SERIAL_NUMBER": "SN456",
        "G2M_GOODWE_INVERTERS_1_IP_ADDRESS": "192.168.1.101",
    }, clear=False):
        config = goodwe2mqtt.read_config("dummy.yaml")
        assert config["mqtt"]["broker_port"] == 8883
        assert config["goodwe"]["inverters"][1]["serial_number"] == "SN456"
