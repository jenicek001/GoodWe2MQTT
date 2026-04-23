"""Phase 0 prototype: verify SEC1000S responds to DT protocol.

Edit HOST to your SEC1000S IP address before running.
Run with: python tools/sec1000s_test.py
"""

import asyncio
import goodwe

HOST = "192.168.33.169"  # <-- set to your SEC1000S IP address
LIMIT = 2500            # W to set as grid export limit


async def main() -> None:
    print(f"Connecting to {HOST} using DT family protocol...")
    inverter = await goodwe.connect(host=HOST, family="DT")
    print(f"Connected: model={inverter.model_name}, serial={inverter.serial_number}")

    print(f"Reading current grid export limit...")
    before = await inverter.get_grid_export_limit()
    print(f"  Before: {before}")

    print(f"Setting grid export limit to {LIMIT}...")
    await inverter.set_grid_export_limit(LIMIT)

    print(f"Reading back grid export limit...")
    after = await inverter.get_grid_export_limit()
    print(f"  After:  {after}")

    if after == LIMIT:
        print("SUCCESS: limit confirmed.")
    else:
        print(f"WARNING: readback value ({after}) does not match requested ({LIMIT}).")


if __name__ == "__main__":
    asyncio.run(main())
