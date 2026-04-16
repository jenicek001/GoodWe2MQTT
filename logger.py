"""Compatibility module for the refactored source layout."""

import src.logger as _logger

config_file = _logger.config_file
log = _logger.log
setup_logging = _logger.setup_logging

__all__ = ["config_file", "log", "setup_logging"]
