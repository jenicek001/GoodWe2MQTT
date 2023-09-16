import logging
import logging.handlers
import yaml
import sys

config_file = "goodwe2mqtt.yaml"

try:
    config = yaml.load(open(config_file), Loader=yaml.FullLoader)
except Exception as e:
    print(f'Error loading YAML file: {e}')
    sys.exit()

log_level = config['logger']['log_level']
log_to_file = bool(config['logger']['log_to_file'])
log_file = config['logger']['log_file']
log_to_console = bool(config['logger']['log_to_console'])
log_rotate = bool(config['logger']['log_rotate'])
log_rotate_size = int(config['logger']['log_rotate_size'])
log_rotate_count = config['logger']['log_rotate_count']

log = logging.getLogger()
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

# Log a message at the INFO level.
# log.info('This is an info message.')

# Log a message at the WARNING level.
# log.warning('This is a warning message.')

# Log a message at the ERROR level.
# log.error('This is an error message.')

#Level	Description
# DEBUG	Detailed information, typically of interest only when debugging.
# INFO	Informational messages that describe what is happening.
# WARNING	Indicates a potential problem.
# ERROR	Indicates a serious problem that may cause the program to fail.
# CRITICAL	Indicates a fatal error that will cause the program to terminate.

