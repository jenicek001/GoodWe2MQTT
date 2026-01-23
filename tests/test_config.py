import sys
from unittest.mock import patch, mock_open, MagicMock
import pytest

# Mock logger module BEFORE importing goodwe2mqtt to avoid side effects
# configuration side effects (reading /var/log/...)
mock_logger_module = MagicMock()
mock_logger_module.log = MagicMock()
sys.modules['logger'] = mock_logger_module

import goodwe2mqtt
import yaml

def test_read_config_success():
    """Test reading a valid configuration file."""
    mock_data = """
    mqtt:
        broker_ip: "127.0.0.1"
    """
    with patch("builtins.open", mock_open(read_data=mock_data)):
        config = goodwe2mqtt.read_config("dummy.yaml")
        assert config['mqtt']['broker_ip'] == "127.0.0.1"

def test_read_config_file_not_found():
    """Test behavior when config file is missing."""
    # We need to ensure log.error is called? Optional but good.
    
    with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
        with pytest.raises(SystemExit):
            goodwe2mqtt.read_config("nonexistent.yaml")
    
    # Verify logger was called
    mock_logger_module.log.error.assert_called()

def test_read_config_invalid_yaml():
    """Test behavior when YAML is invalid."""
    with patch("builtins.open", mock_open(read_data=": invalid yaml")):
        # yaml.load might raise ScannerError or similar, which read_config catches
        # But we need to ensure yaml.load RAISES exception.
        # If we use real yaml, it will.
        
        with pytest.raises(SystemExit):
            goodwe2mqtt.read_config("invalid.yaml")