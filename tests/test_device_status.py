"""The device's own status and a read-only discovery (SmartHomeDesign-EMS REQ-081, 2026-11-20)."""
import json

from device_status import MIN_WINDOW_S, OFFLINE, ONLINE, device_state, status_discovery, window_s


def test_online_while_the_device_answered_within_three_of_its_reads():
    w = window_s(30)
    assert w == 90
    assert device_state(1000.0, 1000.0 + w, w) == ONLINE
    assert device_state(1000.0, 1000.0 + w + 1, w) == OFFLINE


def test_never_offline_sooner_than_a_minute():
    assert window_s(1) == MIN_WINDOW_S


def test_offline_before_the_first_good_read():
    assert device_state(None, 5.0, 60.0) == OFFLINE


def test_the_discovery_announces_a_reading_and_the_status_and_no_command():
    [(topic, payload)] = status_discovery("homeassistant", "9010KETU21CW3302", "GoodWe Inverter 9010KETU21CW3302",
                                          "ET series", "goodwe2mqtt/9010KETU21CW3302/runtime_data", "ppv", "W",
                                          "power", "goodwe2mqtt/9010KETU21CW3302/status")
    cfg = json.loads(payload)
    assert topic == "homeassistant/sensor/9010KETU21CW3302/ppv/config"
    assert cfg["stat_t"] == "goodwe2mqtt/9010KETU21CW3302/runtime_data"
    assert cfg["avty_t"] == "goodwe2mqtt/9010KETU21CW3302/status" and cfg["pl_avail"] == ONLINE
    assert cfg["dev"]["ids"] == ["9010KETU21CW3302"]
    assert not any("cmd" in k or "command" in k for k in cfg)


def test_no_prefix_no_discovery():
    assert status_discovery("", "x", "x", "x", "a", "b", "W", "power", "s") == []


def _inverter():
    from unittest.mock import patch
    import goodwe2mqtt
    from conftest import suppress_ensure_future
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
        return goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN", ip_address="1.2.3.4", mqtt_broker_ip="127.0.0.1", mqtt_broker_port=1883,
            mqtt_username="", mqtt_password="", mqtt_topic_prefix="test", mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="data", mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast", mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="limit")


import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_the_inverter_is_online_only_after_a_good_read_and_offline_when_reads_fail():
    from unittest.mock import AsyncMock, patch
    import goodwe.exceptions
    gw = _inverter()
    assert gw.device_state() == OFFLINE                             # nothing read yet
    gw.inverter = AsyncMock()
    gw.inverter.read_runtime_data.return_value = {"ppv": 5000}
    await gw.read_runtime_data()
    assert gw.device_state() == ONLINE
    gw.inverter.read_runtime_data.side_effect = goodwe.exceptions.MaxRetriesException("Max retries")
    await gw.read_runtime_data()
    with patch("time.monotonic", return_value=gw.last_read_ok + MIN_WINDOW_S + 1):
        assert gw.device_state() == OFFLINE                         # the inverter stopped answering


def test_the_inverters_announcement_is_read_only_and_on_its_runtime_topic():
    gw = _inverter()
    [(topic, payload)] = gw.status_announcements()
    cfg = json.loads(payload)
    assert topic == "homeassistant/sensor/TEST_SN/ppv/config"
    assert cfg["stat_t"] == "test/TEST_SN/data" and cfg["avty_t"] == "test/TEST_SN/status"
    assert not any("cmd" in k or "command" in k for k in cfg)
