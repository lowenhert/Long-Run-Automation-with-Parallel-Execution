import subprocess
from pathlib import Path

class DeviceManager:
    @staticmethod
    def get_connected_devices():
        """Auto-detect all ADB devices"""
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
        lines = result.stdout.strip().split("\n")[1:]  # skip header
        devices = []
        for line in lines:
            if "device" in line:
                device_id = line.split()[0]
                devices.append(device_id)
        return devices or ["172.18.1.75:5555"]  # fallback

    @staticmethod
    def get_device_name(device_id):
        # You can enhance with adb shell getprop ro.product.model
        return device_id.replace(":", "_").replace(".", "_")