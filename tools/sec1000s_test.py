"""Phase 0 prototype: SEC1000S control via its native TCP protocol (port 1234).

The SEC1000S uses a proprietary binary protocol over TCP port 1234.
Protocol fully reverse-engineered at:
  https://github.com/jozef-moravcik-homeassistant/GoodWe-SEC1000S

Command flow to set the export limit:
  1. get_export_limit  (cmd 0x43) — reads total_capacity & current limit
  2. set_export_limit  (cmd 0x42) — writes total_capacity + new limit + phase mode
  3. set_value_mode    (cmd 0x40) — arms VALUE-mode control on the SEC1000S

Run with: python tools/sec1000s_test.py
"""

import socket
import struct

HOST              = "192.168.33.169"
PORT              = 1234
LIMIT_KW          = 2.5    # kW — target grid export limit (2500 W)
TIMEOUT           = 10     # seconds
SCAN_THREE_PHASES = False  # False = measure each phase separately (default)

# Safety guard: never allow a limit at or below this value.
# SEC1000S treats limit <= min as "export disabled", which triggers a grid-export
# penalty.  This script will abort before sending any such command.
MIN_LIMIT_KW      = 0.1   # kW — absolute floor; raise if your tariff requires more


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def _crc(data: bytes) -> bytes:
    """2-byte big-endian CRC: sum of data[2:-2] & 0xFFFF."""
    s = sum(data[2:len(data) - 2]) & 0xFFFF
    return bytes([s >> 8, s & 0xFF])


def _tx_rx(payload: bytes, expected_response_size: int) -> bytes:
    """Send payload over TCP, receive and validate response.

    Returns rx_payload (data[5:]) on success.
    expected_response_size must match data[6] in the response header.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(TIMEOUT)
        s.connect((HOST, PORT))
        s.sendall(payload)

        # Read 7-byte header
        data = b''
        while len(data) < 7:
            chunk = s.recv(7 - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during header read.")
            data += chunk

        response_size = data[6]
        if response_size != expected_response_size:
            raise ValueError(
                f"Unexpected response_size byte: got {response_size}, "
                f"expected {expected_response_size}."
            )

        # Read remaining response bytes
        while len(data) < 7 + response_size:
            chunk = s.recv(7 + response_size - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during data read.")
            data += chunk

    rx_payload = data[5:]   # skip first 5 header bytes (matches upstream library)
    rx_crc = _crc(rx_payload)
    if rx_crc[0] != rx_payload[-2] or rx_crc[1] != rx_payload[-1]:
        raise ValueError(f"CRC error on response: {rx_payload.hex()}")
    return rx_payload


# ---------------------------------------------------------------------------
# SEC1000S commands
# ---------------------------------------------------------------------------

def get_export_limit() -> dict:
    """Read current export limit and device settings (cmd 0x43).

    Response layout (rx_payload offsets):
      [5]       export_limit_control_mode  (0=off, 1=DRED, 2=RCR, 3=VALUE)
      [6:10]    total_capacity             (int32 big-endian, W → kW)
      [10:14]   ratio_ct                   (int32 big-endian)
      [14:18]   export_limit               (int32 big-endian, W → kW)
    """
    payload = b'\x00\x05\x01\x01\x43\x00\x45'
    rx = _tx_rx(payload, expected_response_size=18)
    control_mode_labels = {0: "Deactivated", 1: "DRED", 2: "RCR", 3: "VALUE"}
    mode = rx[5]
    return {
        "control_mode":       mode,
        "control_mode_label": control_mode_labels.get(mode, f"Unknown({mode})"),
        "total_capacity_kw":  round(1e-3 * struct.unpack(">i", rx[6:10])[0], 3),
        "ratio_ct":           round(1e-3 * struct.unpack(">i", rx[10:14])[0], 3),
        "export_limit_kw":    round(1e-3 * struct.unpack(">i", rx[14:18])[0], 3),
    }


def set_export_limit_cmd(limit_kw: float, total_capacity_kw: float,
                         scan_three_phases: bool = False) -> bytes:
    """Set the export limit value (cmd 0x42).

    Returns the raw rx_payload for inspection.
    Raises ValueError if limit_kw is at or below MIN_LIMIT_KW to prevent
    accidentally disabling export.
    """
    if limit_kw <= MIN_LIMIT_KW:
        raise ValueError(
            f"Refusing to set export limit to {limit_kw} kW — this is at or "
            f"below the safety floor MIN_LIMIT_KW={MIN_LIMIT_KW} kW.  "
            "Sending such a value would effectively disable grid export."
        )
    scan_int = 2 if scan_three_phases else 1
    payload = bytearray(16)
    payload[0:5] = b'\x00\x0e\x01\x01\x42'
    payload[5:9]  = struct.pack('!i', int(total_capacity_kw * 1000))
    payload[9:13] = struct.pack('!i', int(limit_kw * 1000))
    payload[13]   = scan_int
    payload[14:16] = _crc(bytes(payload))
    return _tx_rx(bytes(payload), expected_response_size=6)


def enable_value_mode() -> bytes:
    """Arm VALUE-mode export limit control on the SEC1000S (cmd 0x40/0x01).

    This sends the ON variant of the VALUE-mode command (byte[5]=0x01).
    The disable variant (byte[5]=0x02, payload b'\x00\x06\x01\x01\x40\x02\x00\x44')
    is intentionally NOT implemented here — calling it would turn off the
    export limit control entirely and expose the installer to grid penalties.
    """
    payload = b'\x00\x06\x01\x01\x40\x01\x00\x43'
    return _tx_rx(payload, expected_response_size=6)


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------

def main() -> None:
    # Safety check before touching the device
    if LIMIT_KW <= MIN_LIMIT_KW:
        raise SystemExit(
            f"ERROR: LIMIT_KW={LIMIT_KW} kW is at or below the safety floor "
            f"MIN_LIMIT_KW={MIN_LIMIT_KW} kW.  Edit LIMIT_KW to a positive value "
            "above the floor before running this script."
        )

    print(f"=== SEC1000S prototype — {HOST}:{PORT} ===")
    print(f"    Target limit : {LIMIT_KW} kW  (safety floor: >{MIN_LIMIT_KW} kW)\n")

    # Step 1: read current settings (confirms connectivity + gets total_capacity)
    print("--- Step 1: Read current export limit ---")
    settings = get_export_limit()
    for k, v in settings.items():
        print(f"  {k}: {v}")
    total_capacity_kw = settings["total_capacity_kw"]
    if total_capacity_kw <= 0:
        print("  WARNING: total_capacity is 0 — defaulting to 10.0 kW for set command.")
        total_capacity_kw = 10.0

    # Step 2: write the new limit
    print(f"\n--- Step 2: Set export limit to {LIMIT_KW} kW ---")
    rx = set_export_limit_cmd(LIMIT_KW, total_capacity_kw, SCAN_THREE_PHASES)
    print(f"  Response: {rx.hex()}")

    # Step 3: arm VALUE-mode control
    print(f"\n--- Step 3: Enable VALUE-mode control ---")
    rx = enable_value_mode()
    print(f"  Response: {rx.hex()}")

    # Step 4: read back to confirm
    print(f"\n--- Step 4: Read back export limit ---")
    settings2 = get_export_limit()
    readback = settings2["export_limit_kw"]
    print(f"  export_limit_kw: {readback} kW  (requested: {LIMIT_KW} kW)")

    if abs(readback - LIMIT_KW) < 0.05:
        print("\nSUCCESS: limit confirmed on SEC1000S.")
        print("Check ET inverter grid_export_limit values in GoodWe2MQTT to verify propagation.")
    else:
        print(f"\nWARNING: readback ({readback} kW) does not match requested ({LIMIT_KW} kW).")


if __name__ == "__main__":
    main()
