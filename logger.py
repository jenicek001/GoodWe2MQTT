import logging
import logging.handlers
import yaml
import sys

log = logging.getLogger()

def setup_logging(config):
    log_level = config['logger']['log_level']
    log_to_file = bool(config['logger']['log_to_file'])
    log_file = config['logger']['log_file']
    log_to_console = bool(config['logger']['log_to_console'])
    log_rotate = bool(config['logger']['log_rotate'])
    log_rotate_size = int(config['logger']['log_rotate_size'])
    log_rotate_count = config['logger']['log_rotate_count']

    if log_level == 'DEBUG':
        log.setLevel(logging.DEBUG)
    elif log_level == 'INFO':
        log.setLevel(logging.INFO)
    elif log_level == 'WARNING':
        log.setLevel(logging.WARNING)
    elif log_level == 'ERROR':
        log.setLevel(logging.ERROR)
    elif log_level == 'CRITICAL':
        log.setLevel(logging.CRITICAL)
    else:
        log.setLevel(logging.INFO) # default to INFO if log_level is not recognized

    # Clear existing handlers to prevent duplicate logging if called multiple times
    if log.hasHandlers():
        log.handlers.clear()

    if log_to_file:
        if log_rotate:
            # Create a RotatingFileHandler object that rotates log files when they reach 10 MB in size.
            file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=log_rotate_size, backupCount=log_rotate_count)
        else:
            # Add a handler to the log object that writes messages to a file.
            file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s'))
        log.addHandler(file_handler)

    if log_to_console:
        # Add a handler to the log object that prints messages to the console.
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(stream_handler)

config_file = "goodwe2mqtt.yaml"

# Only execute if we can (e.g. file exists), or try/except.
# To preserve original behavior, we try to load.
try:
    config = yaml.load(open(config_file), Loader=yaml.FullLoader)
    setup_logging(config)
except Exception as e:
    # If we are running in a test environment (e.g. pytest), we might not want to exit immediately
    # if the file is missing, unless it's critical.
    # The original code exited.
    # I will verify if we are being imported by a test.
    # But for now, I'll keep the exit, which is why my first test mocks 'open'.
    # If I want to allow importing 'logger' without config in tests, I should change this.
    pass
    # Original code:
    # print(f'Error loading YAML file: {e}')
    # sys.exit()
    # If I keep sys.exit(), my new test `test_setup_logging_function` might fail on import 
    # if it doesn't mock open, because `import logger` runs this block.
    
    # Actually, `test_setup_logging_function` does `import logger`.
    # It does NOT mock open in the test body (only the first test does).
    # So `import logger` will try to read `goodwe2mqtt.yaml`.
    # `goodwe2mqtt.yaml` exists in the root! So it will likely SUCCEED in loading the REAL config.
    # The real config has log level DEBUG.
    # Then `logger.setup_logging(mock_config)` is called with ERROR.
    # So `log.level` should be ERROR.
    # But `setup_logging` needs to clear existing handlers, otherwise we get duplicates.
    # I added `log.handlers.clear()`.
    
    # Wait, the try/except block.
    # If I want to exactly match original behavior, I should print and exit.
    # But for testability, maybe I should wrap this execution in a function or check `__name__`.
    # But `goodwe2mqtt.py` imports it, so it's not `__main__`.
    
    # I will modify the exception handling to print but maybe not exit if we are testing?
    # No, that's magic.
    
    # I will re-enable the exit behavior but maybe only if config is not None?
    # Or I can just let it run. The `goodwe2mqtt.yaml` exists in the repo, so it won't crash.
    
    print(f'Error loading YAML file: {e}')
    # sys.exit() # Commented out for now to allow partial imports in tests without mocks, or re-enable?
    # If I comment it out, the daemon will start without logging config if file is missing. That's a change.
    
    # I'll put it back but use the `sys` import.
    sys.exit()