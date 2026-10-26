"""The state topic confirms a write only with a read-back that matches it (EMS #47, 2026-10-26).

A GW10K-ET applies a written battery current limit at once, but its register can read back the old value for a
while: at 08:15:05 a 0 A write succeeded, the battery went idle, the immediate read-back said 25.0 and that was
published; four minutes later a plain read returned 0.0. The confirmation now re-reads until it matches, and
publishes a disagreement that persists, with the written value, instead of silently publishing the stale one."""
import asyncio  # noqa: I001 - goodwe2mqtt before conftest, as in the other test modules
from unittest.mock import AsyncMock, patch

import pytest

import goodwe2mqtt
from test_battery_limits_and_allowlist import make_gw

TOPIC = "goodwe2mqtt/TEST_SN/state/battery_charge_current_limit_amps"


def reads(*values):
    """A read_setting returning the given values in turn, then the last one forever."""
    seq = list(values)

    async def read(_setting_id):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return AsyncMock(side_effect=read)


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr(goodwe2mqtt.asyncio, "sleep", fake_sleep)
    return slept


async def settle(gw):
    for task in list(gw._confirm_tasks.values()):
        await task


@pytest.mark.asyncio
async def test_a_matching_read_back_is_published_at_once():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = reads(0.0)
    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as pub:
        await gw.handle_set_message("battery_charge_current_limit_amps", "0")
    pub.assert_awaited_once_with(TOPIC, {"battery_charge_current_limit_amps": 0.0})
    assert gw._confirm_tasks == {}


@pytest.mark.asyncio
async def test_a_lagging_read_back_is_re_read_until_it_matches(no_sleep):
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = reads(25.0, 25.0, 25.0, 0.0)          # stale three times, then the written value
    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as pub:
        await gw.handle_set_message("battery_charge_current_limit_amps", "0")
        pub.assert_not_awaited()                                    # the stale 25.0 is never published
        await settle(gw)
    pub.assert_awaited_once_with(TOPIC, {"battery_charge_current_limit_amps": 0.0})
    assert no_sleep[:3] == list(goodwe2mqtt.Goodwe_MQTT.CONFIRM_RETRY_S[:3])


@pytest.mark.asyncio
async def test_a_persisting_disagreement_is_published_with_the_written_value(no_sleep):
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = reads(25.0)
    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as pub, \
         patch.object(goodwe2mqtt, "log") as log:
        await gw.handle_set_message("battery_charge_current_limit_amps", "0")
        await settle(gw)
    pub.assert_awaited_once_with(TOPIC, {"battery_charge_current_limit_amps": 25.0, "written": 0.0})
    assert sum(no_sleep) == sum(goodwe2mqtt.Goodwe_MQTT.CONFIRM_RETRY_S)
    assert any("still reads 25.0 after writing 0.0" in str(c) for c in log.warning.call_args_list)


@pytest.mark.asyncio
async def test_a_new_write_replaces_a_pending_confirmation(no_sleep):
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = reads(25.0)
    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as pub:
        await gw.handle_set_message("battery_charge_current_limit_amps", "0")       # stale: confirmation pending
        first = gw._confirm_tasks["battery_charge_current_limit_amps"]
        gw.inverter.read_setting = reads(25.0)
        await gw.handle_set_message("battery_charge_current_limit_amps", "25")      # matches at once
        await asyncio.gather(first, return_exceptions=True)
    assert first.cancelled()
    assert "battery_charge_current_limit_amps" not in gw._confirm_tasks
    pub.assert_awaited_once_with(TOPIC, {"battery_charge_current_limit_amps": 25.0})


@pytest.mark.asyncio
async def test_a_tenth_of_an_amp_of_rounding_still_matches():
    gw = make_gw()
    gw.inverter = AsyncMock()
    gw.inverter.read_setting = reads(7.3)
    with patch.object(gw, "write_setting", new_callable=AsyncMock, return_value=True), \
         patch.object(gw, "send_mqtt_response", new_callable=AsyncMock) as pub:
        await gw.handle_set_message("battery_charge_current_limit_amps", "7.26")      # written as 7.3
    pub.assert_awaited_once_with(TOPIC, {"battery_charge_current_limit_amps": 7.3})
