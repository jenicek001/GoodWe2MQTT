"""SEC1000S native binary protocol driver (TCP port 1234).

This module is a pure, dependency-free, fully-async implementation of the
proprietary GoodWe SEC1000S binary protocol, reverse-engineered from the
ProMate mobile app by jozef-moravcik:
  https://github.com/jozef-moravcik-homeassistant/GoodWe-SEC1000S

All public API values use **Watts (int)** for power quantities.
Wire values are also Watts (int32 big-endian). Voltage is float (V),
current is float (A).

Protocol frame format (request/response):
  data[0:5]  — header prefix (protocol version, device address, command byte)
  data[5]    — first byte of rx_payload (response code)
  data[6]    — body_size: number of bytes in response body
  data[7:]   — response body (body_size bytes)

The module-internal helper ``_tx_rx`` returns ``data[5:]`` (rx_payload), so
callers index into the *rx_payload* offset space, not the raw data space.
CRC is the 2-byte big-endian sum of rx_payload[2:-2] stored in rx_payload[-2:].
"""

import asyncio
import struct
from typing import Any, Dict

_DEFAULT_PORT: int = 1234
_DEFAULT_TIMEOUT: float = 10.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _crc(data: bytes) -> bytes:
    """Compute 2-byte big-endian checksum over ``data[2:-2]``."""
    s = sum(data[2 : len(data) - 2]) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


async def _tx_rx(
    host: str,
    port: int,
    timeout: float,
    payload: bytes,
    expected_response_size: int,
) -> bytes:
    """Send *payload* via TCP and return the validated rx_payload (``data[5:]``).

    *expected_response_size* must equal ``data[6]`` in the 7-byte response
    header.  CRC of the returned payload is validated before returning.

    Raises:
        ValueError: On unexpected response_size or CRC mismatch.
        asyncio.TimeoutError: If connection or read exceeds *timeout*.
    """
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=timeout
    )
    try:
        writer.write(payload)
        await writer.drain()

        try:
            header = await asyncio.wait_for(reader.readexactly(7), timeout=timeout)
        except asyncio.IncompleteReadError as e:
            raise ValueError(
                f"Command not supported or rejected: device closed after "
                f"{len(e.partial)} bytes (expected 7-byte header)"
            ) from e
        body_size = header[6]
        if body_size != expected_response_size:
            raise ValueError(
                f"Unexpected response_size byte: got {body_size}, "
                f"expected {expected_response_size}."
            )
        body = await asyncio.wait_for(reader.readexactly(body_size), timeout=timeout)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    data = header + body
    rx_payload = data[5:]
    computed = _crc(rx_payload)
    if computed[0] != rx_payload[-2] or computed[1] != rx_payload[-1]:
        raise ValueError(f"CRC mismatch in response: {rx_payload.hex()}")
    return rx_payload


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_telemetry(
    host: str,
    port: int = _DEFAULT_PORT,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Read real-time measurements from the SEC1000S.

    Returns a dict with keys:

    ========================  ========  =============================
    Key                       Unit      Description
    ========================  ========  =============================
    v1, v2, v3                V (float) Phase voltages
    i1, i2, i3                A (float) Phase currents
    p1_watts, p2_watts,       W (int)   Phase active power
    p3_watts
    meters_power_watts        W (int)   Net grid power (+ = export)
    inverters_power_watts     W (int)   Total inverter generation
    load_power_watts          W (int)   House load = inverters - meters
    ========================  ========  =============================
    """
    payload = b"\x00\x05\x01\x01\x0b\x00\x0d"
    rx = await _tx_rx(host, port, timeout, payload, 49)

    def _i32(b: bytes) -> int:
        return struct.unpack(">i", b)[0]

    v1 = round(_i32(rx[5:9]) * 0.1, 1)
    v2 = round(_i32(rx[9:13]) * 0.1, 1)
    v3 = round(_i32(rx[13:17]) * 0.1, 1)
    i1 = round(_i32(rx[17:21]) * 0.01, 2)
    i2 = round(_i32(rx[21:25]) * 0.01, 2)
    i3 = round(_i32(rx[25:29]) * 0.01, 2)
    p1_w = _i32(rx[29:33])
    p2_w = _i32(rx[33:37])
    p3_w = _i32(rx[37:41])
    meters_w = _i32(rx[41:45])
    inverters_w = _i32(rx[45:49])
    load_w = inverters_w - meters_w

    return {
        "v1": v1,
        "v2": v2,
        "v3": v3,
        "i1": i1,
        "i2": i2,
        "i3": i3,
        "p1_watts": p1_w,
        "p2_watts": p2_w,
        "p3_watts": p3_w,
        "meters_power_watts": meters_w,
        "inverters_power_watts": inverters_w,
        "load_power_watts": load_w,
    }


async def get_grid_export_limit(
    host: str,
    port: int = _DEFAULT_PORT,
    timeout: float = _DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Read current grid export-limit settings from the SEC1000S.

    Returns a dict with keys:

    ==========================  =========  ========================================
    Key                         Type       Description
    ==========================  =========  ========================================
    control_mode                int        0=off, 1=DRED, 2=RCR, 3=VALUE
    total_capacity_watts        int (W)    Installed inverter capacity
    grid_export_limit_watts     int (W)    Active grid export limit
    ==========================  =========  ========================================
    """
    payload = b"\x00\x05\x01\x01\x43\x00\x45"
    rx = await _tx_rx(host, port, timeout, payload, 18)

    return {
        "control_mode": int(rx[5]),
        "total_capacity_watts": int(struct.unpack(">i", rx[6:10])[0]),
        "grid_export_limit_watts": int(struct.unpack(">i", rx[14:18])[0]),
    }


async def set_grid_export_limit(
    host: str,
    port: int = _DEFAULT_PORT,
    timeout: float = _DEFAULT_TIMEOUT,
    limit_watts: int = 0,
    total_capacity_watts: int = 0,
    scan_three_phases: bool = False,
) -> bool:
    """Write a new grid export limit to the SEC1000S (cmd 0x42).

    Args:
        host: SEC1000S IP address.
        port: TCP port (default 1234).
        timeout: Per-operation timeout in seconds.
        limit_watts: Target export limit in Watts.
        total_capacity_watts: Inverter total installed capacity in Watts.
        scan_three_phases: If True, sum all three phases simultaneously.

    Returns:
        True if the device acknowledged the command successfully.
    """
    scan_int = 2 if scan_three_phases else 1
    payload = bytearray(16)
    payload[0:5] = b"\x00\x0e\x01\x01\x42"
    payload[5:9] = struct.pack("!i", total_capacity_watts)
    payload[9:13] = struct.pack("!i", limit_watts)
    payload[13] = scan_int
    payload[14:16] = _crc(bytes(payload))

    rx = await _tx_rx(host, port, timeout, bytes(payload), 6)
    return rx in (
        b"\x00\x06\x01\x01\x42\x06\x00\x4A",
        b"\x00\x06\x01\x01\x42\x15\x00\x59",
    )


async def enable_value_mode(
    host: str,
    port: int = _DEFAULT_PORT,
    timeout: float = _DEFAULT_TIMEOUT,
) -> bool:
    """Arm VALUE-mode export-limit control on the SEC1000S (cmd 0x40/0x01).

    Must be called after ``set_grid_export_limit`` to activate the new limit.

    Returns:
        True if the device acknowledged the command successfully.
    """
    payload = b"\x00\x06\x01\x01\x40\x01\x00\x43"
    rx = await _tx_rx(host, port, timeout, payload, 6)
    return rx in (
        b"\x00\x06\x01\x01\x40\x06\x00\x48",
        b"\x00\x06\x01\x01\x40\x15\x00\x57",
    )
