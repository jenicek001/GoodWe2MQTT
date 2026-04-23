"""Phase 0 prototype: SEC1000S control via its native TCP protocol (port 1234).

The SEC1000S does not respond to the goodwe DT UDP protocol (port 8899).
It uses a proprietary binary protocol over TCP port 1234.

Protocol reference:
  - Read status:  https://github.com/GTEC-UDC/goodwe-sec1000-info
  - Write cmds:   reverse-engineered by thibaultmol
                  https://github.com/mletenay/home-assistant-goodwe-inverter/issues/196

Run with: python tools/sec1000s_test.py
"""

import socket
import struct

HOST  = "192.168.33.169"
PORT  = 1234
LIMIT = 2500  # W — target grid export limit (used if set_limit_cmd is discovered)

TIMEOUT = 10  # seconds

# Known commands (reverse-engineered from ProMate app via Wireshark)
# Format: \x00\xLEN \x01\x01 \xREG \xVAL \x00 \xCHECKSUM
# Checksum = sum(bytes[2:6]) & 0xFF
CMD_READ_STATUS          = b'\x00\x05\x01\x01\x0b\x00\x0d'
CMD_ENABLE_EXPORT_LIMIT  = b'\x00\x06\x01\x01\x40\x01\x00\x43'
CMD_DISABLE_EXPORT_LIMIT = b'\x00\x06\x01\x01\x40\x02\x00\x44'


def tcp_send_recv(cmd: bytes, expect_size: int | None = None) -> bytes:
    """Send cmd over TCP and return the full response."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(TIMEOUT)
        s.connect((HOST, PORT))
        s.sendall(cmd)
        data = b''
        try:
            while True:
                chunk = s.recv(256)
                if not chunk:
                    break
                data += chunk
                if expect_size and len(data) >= expect_size:
                    break
        except socket.timeout:
            pass
        return data


def read_status() -> dict:
    """Read current power data from the SEC1000S."""
    data = b''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(TIMEOUT)
        s.connect((HOST, PORT))
        s.sendall(CMD_READ_STATUS)
        while len(data) < 7:
            chunk = s.recv(7 - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during header read.")
            data += chunk
        response_size = data[6]
        if response_size != 49:
            raise ValueError(f"Unexpected response size byte: {response_size} (expected 49).")
        while len(data) < 7 + response_size:
            chunk = s.recv(7 + response_size - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during data read.")
            data += chunk

    print(f"  Raw ({len(data)} bytes): {data.hex()}")
    return {
        "v1":               round(0.1  * struct.unpack(">i", data[0x0A:0x0E])[0], 1),
        "v2":               round(0.1  * struct.unpack(">i", data[0x0E:0x12])[0], 1),
        "v3":               round(0.1  * struct.unpack(">i", data[0x12:0x16])[0], 1),
        "i1":               round(0.01 * struct.unpack(">i", data[0x16:0x1A])[0], 2),
        "i2":               round(0.01 * struct.unpack(">i", data[0x1A:0x1E])[0], 2),
        "i3":               round(0.01 * struct.unpack(">i", data[0x1E:0x22])[0], 2),
        "p1_kw":            round(0.001 * struct.unpack(">i", data[0x22:0x26])[0], 3),
        "p2_kw":            round(0.001 * struct.unpack(">i", data[0x26:0x2A])[0], 3),
        "p3_kw":            round(0.001 * struct.unpack(">i", data[0x2A:0x2E])[0], 3),
        "meter_power_kw":   round(0.001 * struct.unpack(">i", data[0x2E:0x32])[0], 3),
        "inverters_power_kw": round(0.001 * struct.unpack(">i", data[0x32:0x36])[0], 3),
    }


def main() -> None:
    print(f"=== SEC1000S prototype — {HOST}:{PORT} ===\n")

    # 1. Read current status
    print("--- Step 1: Read current status ---")
    try:
        status = read_status()
        for k, v in status.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"  FAILED: {e}")
        print("  Cannot continue — TCP:1234 is not reachable.")
        return

    # 2. Enable export limit
    print("\n--- Step 2: Enable export limit ---")
    resp = tcp_send_recv(CMD_ENABLE_EXPORT_LIMIT)
    print(f"  Response ({len(resp)} bytes): {resp.hex()}")

    # 3. Read status again to see if anything changed
    print("\n--- Step 3: Status after enabling limit ---")
    try:
        status2 = read_status()
        for k, v in status2.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"  FAILED: {e}")

    print("\nDone. Check ET inverter grid_export_limit values in GoodWe2MQTT to confirm effect.")
    print(f"(Limit set to ENABLE; specific wattage={LIMIT}W not yet set — requires further RE.)")


if __name__ == "__main__":
    main()
