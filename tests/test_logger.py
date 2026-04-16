import sys
import logging
from unittest.mock import patch, MagicMock

# Helper to clear logger module from sys.modules
def refresh_logger_module():
    if 'logger' in sys.modules:
        del sys.modules['logger']

def test_logger_initialization():
    refresh_logger_module()
    
    with patch.dict("os.environ", {"G2M_LOG_LEVEL": "INFO", "G2M_LOG_TO_FILE": "false"}, clear=False):
        import logger
        
        # Check if the logger level was set correctly
        assert logger.log.level == logging.INFO

def test_setup_logging_function():
    """Test the setup_logging function directly."""
    refresh_logger_module()

    with patch.dict("os.environ", {"G2M_LOG_TO_FILE": "false"}, clear=False):
         import logger
    
    # Now we test the function with a DIFFERENT config
    mock_config = {
        'logger': {
            'log_level': 'ERROR',
            'log_to_file': False,
            'log_file': 'dummy.log',
            'log_to_console': True,
            'log_rotate': False,
            'log_rotate_size': 1000,
            'log_rotate_count': 1
        }
    }
    
    logger.setup_logging(mock_config)
    
    assert logger.log.level == logging.ERROR

def test_setup_logging_file_rotate():
    """Test file logging with rotation."""
    refresh_logger_module()
    
    with patch.dict("os.environ", {"G2M_LOG_TO_FILE": "false"}, clear=False):
         import logger

    mock_config = {
        'logger': {
            'log_level': 'INFO',
            'log_to_file': True,
            'log_file': 'test.log',
            'log_to_console': False,
            'log_rotate': True,
            'log_rotate_size': 1024,
            'log_rotate_count': 3
        }
    }
    
    with patch('logging.handlers.RotatingFileHandler') as mock_rfh:
        logger.setup_logging(mock_config)
        
        mock_rfh.assert_called_once_with('test.log', maxBytes=1024, backupCount=3)
        # Check if handler was added
        assert any(isinstance(h, MagicMock) for h in logger.log.handlers)
