import sys
from unittest.mock import MagicMock
import pytest

# Mock logger module globally for all tests, before any imports
mock_logger_module = MagicMock()
mock_logger_module.log = MagicMock()
sys.modules['logger'] = mock_logger_module

@pytest.fixture
def mock_logger():
    return mock_logger_module