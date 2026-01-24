import os
import pytest
from unittest.mock import patch, mock_open
import goodwe2mqtt

@pytest.fixture
def mock_yaml_content():
    return """
mqtt:
  broker_ip: "1.2.3.4"
  broker_port: 1883
goodwe:
  inverters:
    - serial_number: "SN123"
      ip_address: "192.168.1.100"
logger:
    log_level: "INFO"
    log_to_file: false
    log_to_console: true
    log_file: "test.log"
    log_rotate: false
    log_rotate_size: 1000
    log_rotate_count: 1
"""

def test_read_config_env_override(mock_yaml_content):
    """Test that environment variables override YAML configuration."""
    with patch("builtins.open", mock_open(read_data=mock_yaml_content)):
        with patch.dict(os.environ, {"G2M_MQTT_BROKER_IP": "10.0.0.1"}):
            config = goodwe2mqtt.read_config("dummy.yaml")
            
            # YAML has 1.2.3.4, Env has 10.0.0.1
            # We expect the env var to take precedence
            assert config["mqtt"]["broker_ip"] == "10.0.0.1"

def test_read_config_env_nested_override(mock_yaml_content):
    """Test overriding nested configuration values via environment variables."""
    # Mapping G2M_GOODWE_INVERTERS_0_IP_ADDRESS to config['goodwe']['inverters'][0]['ip_address']
    # This might be complex to implement generically. 
    # For now, let's stick to simple flat overrides if possible, or defined mappings.
    # The spec examples: G2M_MQTT_HOST (which maps to mqtt.broker_ip?)
    # The spec says: G2M_MQTT_HOST, G2M_INVERTER_IP.
    
    # If we stick to specific overrides logic:
    with patch("builtins.open", mock_open(read_data=mock_yaml_content)):
        with patch.dict(os.environ, {"G2M_MQTT_BROKER_PORT": "8883"}):
            config = goodwe2mqtt.read_config("dummy.yaml")
            assert config["mqtt"]["broker_port"] == 8883 # Should be cast to int if possible, or str depending on impl

