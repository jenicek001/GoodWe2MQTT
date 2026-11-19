"""Tests for DT (grid-only) inverter support.

A DT/MS/D-NS/XS inverter differs from an ET in ways this bridge has to respect:
the goodwe library's DT.read_settings_data() has none of the per-setting error
tolerance its ET counterpart has, so one unimplemented register aborts it; a DT
has no battery, no work mode and no EMS mode; and a three-phase DT reports its
grid export limit as a percentage rather than a number of watts.
"""
import asyncio  # noqa: I001 - goodwe2mqtt before conftest, as in the other test modules
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import goodwe2mqtt
from goodwe.inverter import Sensor, SensorKind
from conftest import suppress_ensure_future


def _setting(id_, unit=""):
    """A stand-in for a goodwe Sensor as returned by Inverter.settings()."""
    return Sensor(id_, 0, id_, 2, unit, SensorKind.GRID)


def make_gw(family=""):
    """Create a Goodwe_MQTT instance with asyncio tasks suppressed."""
    with patch("asyncio.ensure_future", side_effect=suppress_ensure_future):
        return goodwe2mqtt.Goodwe_MQTT(
            serial_number="TEST_SN",
            ip_address="1.2.3.4",
            mqtt_broker_ip="127.0.0.1",
            mqtt_broker_port=1883,
            mqtt_username="user",
            mqtt_password="pass",
            mqtt_topic_prefix="goodwe2mqtt",
            mqtt_control_topic_postfix="control",
            mqtt_runtime_data_topic_postfix="runtime_data",
            mqtt_runtime_data_interval_seconds=5,
            mqtt_fast_runtime_data_topic_postfix="fast_runtime_data",
            mqtt_fast_runtime_data_interval_seconds=1,
            mqtt_grid_export_limit_topic_postfix="grid_export_limit",
            family=family,
        )


def make_dt_inverter(settings, values=None, missing=()):
    """An inverter that advertises `settings` and rejects the ids in `missing`."""
    inverter = MagicMock()
    inverter.settings.return_value = [_setting(s, "%" if s == "grid_export_limit" else "")
                                     for s in settings]
    values = values or {}

    async def read_setting(setting_id):
        if setting_id in missing:
            raise ValueError(f'Unknown sensor/setting "{setting_id}"')
        return values.get(setting_id, 1)

    inverter.read_setting = AsyncMock(side_effect=read_setting)
    inverter.write_setting = AsyncMock()
    return inverter


# ---------------------------------------------------------------------------
# read_settings_data – the failure that broke DT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_settings_data_falls_back_when_bulk_read_raises():
    """A DT bulk read aborts on the first unsupported register; the bridge reads them one by one."""
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(
        ["grid_export_limit", "shadow_scan_pv1", "shadow_scan_pv2"],
        values={"grid_export_limit": 100, "shadow_scan_pv1": 0},
        missing=("shadow_scan_pv2",),
    )
    gw.inverter.read_settings_data = AsyncMock(
        side_effect=ValueError('Unknown sensor/setting "shadow_scan_pv2"'))

    settings = await gw.read_settings_data()

    assert settings is not None
    assert settings["grid_export_limit"] == 100
    assert settings["shadow_scan_pv2"] is None       # unsupported, not fatal
    assert settings["shadow_scan_pv1"] == 0


@pytest.mark.asyncio
async def test_read_settings_data_uses_bulk_read_when_it_works():
    """An ET whose bulk read succeeds is read in one call, as before."""
    gw = make_gw()
    gw.inverter = MagicMock()
    gw.inverter.read_settings_data = AsyncMock(return_value={"work_mode": 0})

    settings = await gw.read_settings_data()

    assert settings == {"work_mode": 0}


@pytest.mark.asyncio
async def test_read_settings_data_returns_none_when_nothing_can_be_read():
    """If even listing the settings fails there is nothing to report."""
    gw = make_gw()
    gw.inverter = MagicMock()
    gw.inverter.read_settings_data = AsyncMock(side_effect=Exception("no response"))
    gw.inverter.settings = MagicMock(side_effect=Exception("no response"))

    assert await gw.read_settings_data() is None


# ---------------------------------------------------------------------------
# Unsupported commands are rejected, not passed to the library
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("setting_id", [
    "work_mode",
    "battery_charge_current_limit_amps",
    "battery_discharge_current_limit_amps",
    "ems_mode",
    "ems_power_limit_watts",
])
async def test_set_rejects_settings_a_dt_does_not_have(setting_id):
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(["grid_export_limit"])

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message(setting_id, "1")

    mock_write.assert_not_awaited()
    gw.inverter.write_setting.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_rejects_settings_a_dt_does_not_have():
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(["grid_export_limit"])

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.handle_get_message("work_mode")

    gw.inverter.read_setting.assert_not_awaited()
    mock_pub.assert_not_awaited()


@pytest.mark.asyncio
async def test_grid_export_limit_still_writable_on_a_dt():
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(["grid_export_limit"], values={"grid_export_limit": 80})
    gw.grid_export_limit_unit = "%"

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write:
        await gw.handle_set_message("grid_export_limit_watts", "80")

    mock_write.assert_awaited_once_with("grid_export_limit", 80)


# ---------------------------------------------------------------------------
# The export limit is a percentage on a three-phase DT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_percent_export_limit_accepts_up_to_200():
    """The HA integration allows 0-200% for a percent-setting inverter; so does this bridge."""
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(["grid_export_limit"])
    gw.grid_export_limit_unit = "%"

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write:
        await gw.handle_set_message("grid_export_limit_watts", "200")

    mock_write.assert_awaited_once_with("grid_export_limit", 200)


@pytest.mark.asyncio
async def test_percent_export_limit_rejects_above_200():
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(["grid_export_limit"])
    gw.grid_export_limit_unit = "%"

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("grid_export_limit_watts", "201")

    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_watt_export_limit_keeps_its_own_range():
    """An ET still accepts 0-10000 W and no more."""
    gw = make_gw()
    gw.inverter = make_dt_inverter(["grid_export_limit"])
    gw.grid_export_limit_unit = "W"

    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True) as mock_write:
        await gw.handle_set_message("grid_export_limit_watts", "10000")
    mock_write.assert_awaited_once_with("grid_export_limit", 10000)

    with patch.object(gw, "write_setting", new_callable=AsyncMock) as mock_write:
        await gw.handle_set_message("grid_export_limit_watts", "10001")
    mock_write.assert_not_awaited()


@pytest.mark.asyncio
async def test_percent_export_limit_is_not_reinterpreted_as_signed():
    """A percentage is unsigned: 255 is 255%, not -1."""
    gw = make_gw(family="DT")
    gw.inverter = MagicMock()
    gw.inverter.get_grid_export_limit = AsyncMock(return_value=255)
    gw.grid_export_limit_unit = "%"

    assert await gw.get_grid_export_limit() == 255


@pytest.mark.asyncio
async def test_watt_export_limit_is_still_reinterpreted_as_signed():
    """An ET stores a negative watt limit two's complement, as before."""
    gw = make_gw()
    gw.inverter = MagicMock()
    gw.inverter.get_grid_export_limit = AsyncMock(return_value=65486)
    gw.grid_export_limit_unit = "W"

    assert await gw.get_grid_export_limit() == -50


@pytest.mark.asyncio
async def test_export_limit_payload_carries_its_unit():
    """The published payload says whether the number is watts or a percentage."""
    gw = make_gw(family="DT")
    gw.grid_export_limit_unit = "%"

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.send_mqtt_export_limit(100)

    payload = mock_pub.call_args.args[1]
    assert payload["grid_export_limit_watts"] == 100
    assert payload["unit"] == "%"


# ---------------------------------------------------------------------------
# HA discovery only offers what the inverter has
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dt_discovery_publishes_only_the_export_limit():
    """A DT gets no battery, work mode or EMS entities — they would be dead in Home Assistant."""
    gw = make_gw(family="DT")
    gw.family_name = "DT"
    gw.grid_export_limit_unit = "%"
    gw.inverter = make_dt_inverter(["grid_export_limit"])

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    topics = [c.args[0] for c in mock_pub.call_args_list]
    assert topics == ["homeassistant/number/TEST_SN_grid_export_limit_watts/config"]
    payload = mock_pub.call_args.args[1]
    assert payload["unit_of_measurement"] == "%"
    assert (payload["min"], payload["max"]) == (0, 200)
    assert payload["device"]["model"] == "DT series"


@pytest.mark.asyncio
async def test_et_discovery_still_publishes_all_six_entities():
    gw = make_gw()
    gw.inverter = make_dt_inverter([
        "grid_export_limit", "work_mode", "ems_mode",
        "battery_charge_current", "battery_discharge_current",
    ])
    gw.grid_export_limit_unit = "W"

    with patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as mock_pub:
        await gw.publish_ha_discovery()

    topics = [c.args[0] for c in mock_pub.call_args_list]
    assert len(topics) == 6
    assert "homeassistant/select/TEST_SN_work_mode/config" in topics
    assert "homeassistant/number/TEST_SN_ems_power_limit_watts/config" in topics


# ---------------------------------------------------------------------------
# main_loop keeps publishing when the settings read fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_loop_publishes_runtime_data_when_settings_fail():
    """A failing settings read must not stop runtime data being published."""
    gw = make_gw(family="DT")
    gw.inverter = make_dt_inverter(["grid_export_limit"])
    gw.read_settings_data = AsyncMock(return_value=None)
    gw.read_runtime_data = AsyncMock(return_value={"ppv": 42, "serial_number": "TEST_SN"})

    published = []
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    async def publish(topic, payload=None):
        published.append(topic)

    mock_client.publish = AsyncMock(side_effect=publish)

    # main_loop treats CancelledError as "shut down quietly", so it returns after one pass.
    with patch("goodwe2mqtt.aiomqtt.Client", return_value=mock_client), \
         patch("asyncio.sleep", side_effect=asyncio.CancelledError):
        await gw.main_loop()

    assert gw.mqtt_fast_runtime_data_topic in published
