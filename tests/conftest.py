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


def suppress_ensure_future(coro):
    """Side-effect for patching asyncio.ensure_future in tests.

    Closes the coroutine immediately so Python does not emit
    "coroutine was never awaited" RuntimeWarnings during GC.
    """
    coro.close()
    return MagicMock()