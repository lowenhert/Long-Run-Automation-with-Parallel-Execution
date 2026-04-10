import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)


class DeviceController:
    """Controls Android TV device via ADB commands"""

    def __init__(self, device_id):
        self.device_id = device_id

    def _run_adb_command(self, command):
        """Execute ADB command on the device"""
        full_command = ["adb", "-s", self.device_id] + command
        try:
            result = subprocess.run(full_command, capture_output=True, text=True, timeout=10)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"

    def home(self):
        """Navigate to home screen"""
        success, _, _ = self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_HOME"])
        return success

    def up(self):
        """Navigate upwards"""
        success, _, _ = self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_DPAD_UP"])

    def left(self,count=1):
        """Navigate to left"""
        for _ in range(count):
            success, _, _ = self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_DPAD_LEFT"])


    def back(self):
        """Navigate to previous screen by pressing back"""
        success, _, _ = self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_BACK"])


    def navigate_down(self, count=1):
        """Navigate down by count"""
        for _ in range(count):
            self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_DPAD_DOWN"])

    def navigate_right(self, count=1):
        """Navigate right by count"""
        for _ in range(count):
            self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_DPAD_RIGHT"])

    def select(self):
        """Press select/enter"""
        success, _, _ = self._run_adb_command(["shell", "input", "keyevent", "KEYCODE_DPAD_CENTER"])
        return success

    def long_press_right(self):
        """Long press RIGHT key"""
        success, _, _ = self._run_adb_command(["shell", "input", "keyevent", "--longpress", "KEYCODE_DPAD_RIGHT"])
        return success

    def take_screenshot(self, save_path=None):
        """Take screenshot, save to disk, and return the path"""
        if not save_path:
            save_path = f"screenshot_{int(time.time())}.png"

        self._run_adb_command(["shell", "screencap", "-p", "/sdcard/screenshot.png"])
        success, _, _ = self._run_adb_command(["pull", "/sdcard/screenshot.png", str(save_path)])

        if success:
            return save_path
        return None

    def take_screenshot_bytes(self) -> bytes:
        """
        Return the current screen as raw PNG bytes without writing to disk.

        Uses `adb exec-out` which streams binary output directly — faster and
        cleaner than screencap → pull → read cycle.  The bytes can be passed
        straight into OcrLibrary.extract_text_from_region_bytes() or any other
        library that accepts PNG bytes (e.g. LogoCompareLibrary).
        
        Includes retry logic for network devices that may have latency.
        """
        full_command = ["adb", "-s", self.device_id, "exec-out", "screencap", "-p"]
        max_retries = 3
        timeout_seconds = 20  # Increased timeout for network devices
        
        for attempt in range(max_retries):
            try:
                result = subprocess.run(
                    full_command,
                    capture_output=True,   # stdout = PNG bytes, stderr = error text
                    timeout=timeout_seconds,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"screencap failed (exit {result.returncode}): "
                        f"{result.stderr.decode(errors='replace').strip()}"
                    )
                if not result.stdout:
                    raise RuntimeError("screencap returned empty output")
                return result.stdout

            except subprocess.TimeoutExpired:
                if attempt < max_retries - 1:
                    log.warning(
                        f"[SCREENSHOT] Attempt {attempt + 1}/{max_retries} timed out, retrying..."
                    )
                    time.sleep(1)  # Brief pause before retry
                    continue
                raise RuntimeError(
                    f"take_screenshot_bytes timed out after {max_retries} attempts on device {self.device_id}"
                )
            except Exception as e:
                if attempt < max_retries - 1:
                    log.warning(
                        f"[SCREENSHOT] Attempt {attempt + 1}/{max_retries} failed: {e}, retrying..."
                    )
                    time.sleep(1)
                    continue
                raise

    def get_screen_size(self):
        """Get device screen dimensions"""
        success, output, _ = self._run_adb_command(["shell", "wm", "size"])
        if success and "Physical size:" in output:
            size_str = output.split("Physical size: ")[1].strip()
            width, height = map(int, size_str.split("x"))
            return width, height
        return 1920, 1080  # Default fallback