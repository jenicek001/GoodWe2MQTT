from unittest.mock import patch, mock_open
import pytest
import goodwe2mqtt

def test_read_config_success():
    """Test reading a valid configuration file."""
    mock_data = """
    mqtt:
        broker_ip: "127.0.0.1"
    """
    with patch("builtins.open", mock_open(read_data=mock_data)):
        config = goodwe2mqtt.read_config("dummy.yaml")
        assert config['mqtt']['broker_ip'] == "127.0.0.1"

def test_read_config_file_not_found(mock_logger):
    """Test behavior when config file is missing."""
    with patch("builtins.open", side_effect=FileNotFoundError("File not found")):
        with pytest.raises(SystemExit):
            goodwe2mqtt.read_config("nonexistent.yaml")
    
    # Verify logger was called
    mock_logger.log.error.assert_called()

def test_read_config_invalid_yaml():
    """Test behavior when YAML is invalid."""
    with patch("builtins.open", mock_open(read_data=": invalid yaml")):
        with pytest.raises(SystemExit):
            goodwe2mqtt.read_config("invalid.yaml")
