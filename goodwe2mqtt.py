"""Compatibility entrypoint for the refactored source layout."""

import src.goodwe2mqtt as _app

Goodwe_MQTT = _app.Goodwe_MQTT
aiomqtt = _app.aiomqtt
config_file = _app.config_file
dump_to_json = _app.dump_to_json
get_timezone_aware_local_time = _app.get_timezone_aware_local_time
main = _app.main
override_config_from_env = _app.override_config_from_env
read_config = _app.read_config


if __name__ == "__main__":
    import asyncio

    _config = read_config(config_file)
    asyncio.run(main(_config))
