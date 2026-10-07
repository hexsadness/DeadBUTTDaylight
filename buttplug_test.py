"""Standalone Intiface/Buttplug connection test."""
import asyncio
from buttplug import ButtplugClient, DeviceOutputCommand, OutputType

INTIFACE_ADDRESS = "ws://127.0.0.1:12345"
SCAN_TIME = 10
TEST_STRENGTH = 0.30
TEST_DURATION = 2

async def main():
    client = ButtplugClient("DBD Haptics Test")
    try:
        print("Connecting to Intiface Central...")
        await client.connect(INTIFACE_ADDRESS)
        print("Connected. Scanning for devices...")
        await client.start_scanning()
        await asyncio.sleep(SCAN_TIME)
        await client.stop_scanning()
        devices = list(client.devices.values())
        if not devices:
            print("No devices found.")
            return
        for device in devices:
            print(f"Found: {device.name}")
            if not device.has_output(OutputType.VIBRATE):
                print("  Vibration not supported; skipping.")
                continue
            print(f"  Testing at {TEST_STRENGTH:.0%} for {TEST_DURATION}s")
            await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, TEST_STRENGTH))
            await asyncio.sleep(TEST_DURATION)
            await device.stop()
    finally:
        for device in client.devices.values():
            try:
                await device.stop()
            except Exception:
                pass
        try:
            await client.disconnect()
        except Exception:
            pass
        print("Stopped and disconnected.")

if __name__ == "__main__":
    asyncio.run(main())
