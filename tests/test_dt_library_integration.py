"""Integration test against the real goodwe DT class.

The unit tests use mocks that mimic the library's behaviour; this one drives
`Goodwe_MQTT.read_settings_data()` against an actual `goodwe.dt.DT` instance
whose socket layer is faked, so the double-fault it was written for is
exercised for real: the library's own `DT.read_settings_data()` aborts on the
first register the inverter rejects, and the bridge has to recover from that.
"""
import pytest
from unittest.mock import patch
import goodwe2mqtt
from goodwe.dt import DT
from goodwe.exceptions import RequestRejectedException
from goodwe.modbus import ILLEGAL_DATA_ADDRESS
from goodwe.protocol import ProtocolCommand, ProtocolResponse
from conftest import suppress_ensure_future

# Registers a GW6000-DT-class inverter does not implement: the library reads
# these in read_settings_data() and the inverter answers "illegal data address".
UNSUPPORTED_REGISTERS = {40326, 40347, 40352, 40362, 40345}


class FakeTransportDT(DT):
    """A DT inverter whose UDP transport answers, or rejects, without a network."""

    def __init__(self):
        super().__init__("127.0.0.1", 8899)
        self.rejected: list[str] = []

    async def _read_from_socket(self, command: ProtocolCommand) -> ProtocolResponse:
        # The device-version read is what tells the library whether this is a
        # single or three phase inverter, so it must succeed with sane content.
        if command == self._READ_DEVICE_VERSION_INFO:
            return ProtocolResponse(
                bytes.fromhex("aa557f0000000000000000000000000000000000000000000000000000000000"),
                command,
            )
        raise RequestRejectedException(ILLEGAL_DATA_ADDRESS)


def make_gw():
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
            family="DT",
        )


@pytest.mark.asyncio
async def test_library_dt_settings_read_really_does_abort():
    """Confirm the failure this change exists for, straight from the library."""
    inverter = FakeTransportDT()
    await inverter.read_device_info()

    with pytest.raises(ValueError):
        await inverter.read_settings_data()


@pytest.mark.asyncio
async def test_bridge_survives_the_library_abort():
    """The bridge reads the advertised settings one by one when the bulk read aborts."""
    inverter = FakeTransportDT()
    await inverter.read_device_info()
    advertised = {s.id_ for s in inverter.settings()}
    assert advertised, "the fake DT should advertise settings to begin with"

    gw = make_gw()
    gw.inverter = inverter

    settings = await gw.read_settings_data()

    # The whole point: an unsupported register no longer makes the read fail outright.
    assert settings is not None
    assert settings, "the settings read should still report the inverter's settings"
    # The register that used to kill the whole read is reported as unsupported rather than raising.
    assert settings.get("shadow_scan_pv2") is None
    # The library pops each setting it rejects from settings() as it goes, so the fallback covers
    # whatever is still advertised; it never invents settings the inverter does not have.
    assert set(settings) <= advertised


@pytest.mark.asyncio
async def test_bridge_detects_a_dt_has_no_battery_or_modes():
    """Capability probing against a real DT instance."""
    inverter = FakeTransportDT()
    await inverter.read_device_info()
    gw = make_gw()
    gw.inverter = inverter

    assert gw._supports_battery() is False
    assert gw._supports_work_mode() is False
    assert gw._supports_ems_mode() is False
    assert gw._setting_supported("battery_charge_current_limit_amps") is False
    assert gw._setting_supported("work_mode") is False
    assert gw._setting_supported("grid_export_limit_watts") is True
