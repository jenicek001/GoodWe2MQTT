"""Unit tests for sec1000s_protocol — pure protocol logic, no network I/O."""
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sec1000s_protocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_get_grid_export_limit_response(
    control_mode: int,
    total_capacity_w: int,
    export_limit_w: int,
) -> tuple:
    """Build (header_bytes, body_bytes) for a get_grid_export_limit response.

    Matches the frame layout consumed by ``_tx_rx``:
      - ``readexactly(7)`` → header_bytes
      - ``readexactly(18)`` → body_bytes
    """
    # rx_payload = data[5:], length = 2 + 18 = 20 bytes
    rx = bytearray(20)
    rx[0] = 0x00   # data[5] – response code
    rx[1] = 18     # data[6] – body_size = expected_response_size
    # data fields at rx offsets 5..17
    rx[5] = control_mode
    struct.pack_into(">i", rx, 6, total_capacity_w)
    # rx[10:14] = ratio_ct (zero)
    struct.pack_into(">i", rx, 14, export_limit_w)
    # CRC over rx[2:18]
    s = sum(rx[2:18]) & 0xFFFF
    rx[18] = s >> 8
    rx[19] = s & 0xFF

    header_bytes = bytes([0x00, 0x19, 0x01, 0x01, 0x43, rx[0], rx[1]])  # data[0:7]
    body_bytes = bytes(rx[2:20])  # data[7:25] — 18 bytes
    return header_bytes, body_bytes


def build_telemetry_response(
    v1_raw: int = 2300,  # 230.0 V
    i1_raw: int = 1000,  # 10.00 A
    p1_w: int = 2300,
    meters_w: int = 500,
    inverters_w: int = 5000,
) -> tuple:
    """Build (header_bytes, body_bytes) for a get_telemetry response."""
    # rx_payload length = 2 + 49 = 51 bytes
    rx = bytearray(51)
    rx[0] = 0x00   # data[5]
    rx[1] = 49     # data[6] – body_size
    # v1..v3 at rx[5..17], all same for simplicity
    struct.pack_into(">i", rx, 5, v1_raw)
    struct.pack_into(">i", rx, 9, v1_raw)
    struct.pack_into(">i", rx, 13, v1_raw)
    # i1..i3 at rx[17..29]
    struct.pack_into(">i", rx, 17, i1_raw)
    struct.pack_into(">i", rx, 21, i1_raw)
    struct.pack_into(">i", rx, 25, i1_raw)
    # p1..p3 at rx[29..41]
    struct.pack_into(">i", rx, 29, p1_w)
    struct.pack_into(">i", rx, 33, p1_w)
    struct.pack_into(">i", rx, 37, p1_w)
    # meters_power at rx[41..45], inverters_power at rx[45..49]
    struct.pack_into(">i", rx, 41, meters_w)
    struct.pack_into(">i", rx, 45, inverters_w)
    # CRC over rx[2:49]
    s = sum(rx[2:49]) & 0xFFFF
    rx[49] = s >> 8
    rx[50] = s & 0xFF

    header_bytes = bytes([0x00, 0x36, 0x01, 0x01, 0x0B, rx[0], rx[1]])  # data[0:7]
    body_bytes = bytes(rx[2:51])  # data[7:56] — 49 bytes
    return header_bytes, body_bytes


def make_mock_stream(header: bytes, body: bytes):
    """Return (mock_reader, mock_writer) that serve *header* then *body*."""
    mock_reader = MagicMock()
    mock_reader.readexactly = AsyncMock(side_effect=[header, body])
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    return mock_reader, mock_writer


# ---------------------------------------------------------------------------
# _crc
# ---------------------------------------------------------------------------

def test_crc_get_grid_export_limit_command():
    """CRC of the hardcoded get_grid_export_limit command should match its last 2 bytes."""
    payload = b"\x00\x05\x01\x01\x43\x00\x45"
    crc = sec1000s_protocol._crc(payload)
    assert crc == bytes([payload[-2], payload[-1]])


def test_crc_get_telemetry_command():
    """CRC of the hardcoded get_telemetry command should match its last 2 bytes."""
    payload = b"\x00\x05\x01\x01\x0b\x00\x0d"
    crc = sec1000s_protocol._crc(payload)
    assert crc == bytes([payload[-2], payload[-1]])


def test_crc_enable_value_mode_command():
    """CRC of the hardcoded enable_value_mode command should match its last 2 bytes."""
    payload = b"\x00\x06\x01\x01\x40\x01\x00\x43"
    crc = sec1000s_protocol._crc(payload)
    assert crc == bytes([payload[-2], payload[-1]])


# ---------------------------------------------------------------------------
# get_grid_export_limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_export_limit_parses_response():
    """get_grid_export_limit should correctly parse a valid response frame."""
    header, body = build_get_grid_export_limit_response(
        control_mode=3, total_capacity_w=10000, export_limit_w=3000
    )
    # _tx_rx returns data[5:] = header[5:] + body
    rx_payload = header[5:] + body

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=rx_payload):
        result = await sec1000s_protocol.get_grid_export_limit("192.168.1.1")

    assert result["control_mode"] == 3
    assert result["total_capacity_watts"] == 10000
    assert result["ratio_ct_raw"] == 0
    assert result["grid_export_limit_watts"] == 3000


@pytest.mark.asyncio
async def test_get_export_limit_uses_correct_command():
    """get_grid_export_limit should send cmd 0x43."""
    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock) as mock_tx:
        # Build a minimal valid rx_payload (20 bytes with correct CRC)
        rx = bytearray(20)
        rx[1] = 18
        s = sum(rx[2:18]) & 0xFFFF
        rx[18] = s >> 8
        rx[19] = s & 0xFF
        mock_tx.return_value = bytes(rx)

        await sec1000s_protocol.get_grid_export_limit("192.168.1.1", port=1234, timeout=5.0)

    call_args = mock_tx.call_args
    assert call_args[0][3] == b"\x00\x05\x01\x01\x43\x00\x45"
    assert call_args[0][4] == 18  # expected_response_size


# ---------------------------------------------------------------------------
# get_telemetry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_telemetry_parses_response():
    """get_telemetry should correctly parse voltage, current, power fields."""
    header, body = build_telemetry_response(
        v1_raw=2300,      # 230.0 V
        i1_raw=500,       # 5.00 A
        p1_w=1150,        # 1150 W per phase
        meters_w=500,
        inverters_w=4500,
    )
    # _tx_rx returns data[5:] = header[5:] + body
    rx_payload = header[5:] + body

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=rx_payload):
        result = await sec1000s_protocol.get_telemetry("192.168.1.1")

    assert result["v1"] == pytest.approx(230.0, abs=0.1)
    assert result["i1"] == pytest.approx(5.00, abs=0.01)
    assert result["p1_watts"] == 1150
    assert result["meters_power_watts"] == 500
    assert result["inverters_power_watts"] == 4500
    assert result["load_power_watts"] == 4000  # inverters - meters


# ---------------------------------------------------------------------------
# set_grid_export_limit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_export_limit_builds_correct_payload():
    """set_grid_export_limit should send the correct binary payload."""
    rx_success = b"\x00\x06\x01\x01\x42\x06\x00\x4A"

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=rx_success) as mock_tx:
        result = await sec1000s_protocol.set_grid_export_limit(
            "192.168.1.1", port=1234, timeout=10.0,
            limit_watts=3000,
            total_capacity_watts=10000,
            scan_three_phases=False,
        )

    assert result is True
    call_args = mock_tx.call_args[0]
    payload = call_args[3]

    assert payload[0:5] == b"\x00\x0e\x01\x01\x42"
    assert struct.unpack(">i", payload[5:9])[0] == 10000   # total_capacity_watts on wire
    assert struct.unpack(">i", payload[9:13])[0] == 3000   # limit_watts on wire
    assert payload[13] == 1  # scan_three_phases=False → 1
    # Verify CRC
    expected_crc = sec1000s_protocol._crc(payload)
    assert payload[14:16] == expected_crc


@pytest.mark.asyncio
async def test_set_export_limit_scan_three_phases():
    """set_grid_export_limit with scan_three_phases=True should set scan byte to 2."""
    rx_success = b"\x00\x06\x01\x01\x42\x06\x00\x4A"

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=rx_success) as mock_tx:
        await sec1000s_protocol.set_grid_export_limit(
            "192.168.1.1", limit_watts=3000, total_capacity_watts=10000,
            scan_three_phases=True,
        )
    payload = mock_tx.call_args[0][3]
    assert payload[13] == 2  # scan_three_phases=True → 2


@pytest.mark.asyncio
async def test_set_export_limit_returns_false_on_unknown_response():
    """set_grid_export_limit should return False if the response is not a known ACK."""
    # Build a non-success response with valid CRC
    rx = bytearray(8)
    rx[0] = 0x00
    rx[1] = 0x06
    rx[2:6] = b"\x01\x01\x42\xFF"  # status 0xFF = unknown
    s = sum(rx[2:6]) & 0xFFFF
    rx[6] = s >> 8
    rx[7] = s & 0xFF

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=bytes(rx)):
        result = await sec1000s_protocol.set_grid_export_limit(
            "192.168.1.1", limit_watts=3000, total_capacity_watts=10000
        )

    assert result is False


# ---------------------------------------------------------------------------
# enable_value_mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enable_value_mode_sends_correct_command():
    """enable_value_mode should send cmd 0x40/0x01."""
    rx_success = b"\x00\x06\x01\x01\x40\x06\x00\x48"

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=rx_success) as mock_tx:
        result = await sec1000s_protocol.enable_value_mode("192.168.1.1")

    assert result is True
    call_args = mock_tx.call_args[0]
    assert call_args[3] == b"\x00\x06\x01\x01\x40\x01\x00\x43"
    assert call_args[4] == 6  # expected_response_size


@pytest.mark.asyncio
async def test_enable_value_mode_returns_false_on_unknown_response():
    """enable_value_mode should return False for an unrecognised response."""
    rx = bytearray(8)
    rx[0:2] = b"\x00\x06"
    rx[2:6] = b"\x01\x01\x40\xFF"
    s = sum(rx[2:6]) & 0xFFFF
    rx[6] = s >> 8
    rx[7] = s & 0xFF

    with patch("sec1000s_protocol._tx_rx", new_callable=AsyncMock, return_value=bytes(rx)):
        result = await sec1000s_protocol.enable_value_mode("192.168.1.1")

    assert result is False
