import logging
import os
import subprocess
import time
from subprocess import TimeoutExpired

import cv2
import numpy as np
from robot.api.deco import keyword

log = logging.getLogger(__name__)


class BlackScreenCheck:

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, screenshot_dir: str = "./screenshots", device_name: str = ""):
        self.screenshot_dir = screenshot_dir
        self.device_name = device_name

        self.consecutive_black_screens = 0
        self.max_consecutive_allowed = 2
        self.total_checks = 0
        self.black_screen_count = 0

        os.makedirs(self.screenshot_dir, exist_ok=True)

        log.info(
            f"BlackScreenCheck initialized — dir='{self.screenshot_dir}' "
            f"device='{self.device_name}'"
        )

    # ─────────────────────────────────────────────
    # ADB EXECUTION
    # ─────────────────────────────────────────────

    def _adb(self, *args, check=True, timeout=30):
        """Run an ADB command, scoped to self.device_name when set."""
        cmd = ["adb"]
        if self.device_name:
            cmd += ["-s", self.device_name]
        cmd += list(args)
        
        log.debug(f"ADB: {' '.join(cmd)}")
        return subprocess.run(cmd, check=check, capture_output=True, timeout=timeout)

    def _adb_reconnect(self):
        """Disconnect and reconnect the ADB device to reset a stale connection."""
        if not self.device_name:
            return
        try:
            log.warning(f"[ADB] Reconnecting device: {self.device_name}")
            subprocess.run(["adb", "disconnect", self.device_name],
                           capture_output=True, timeout=10)
            time.sleep(1)
            subprocess.run(["adb", "connect", self.device_name],
                           capture_output=True, timeout=10)
            time.sleep(2)
            log.info(f"[ADB] Reconnect complete for: {self.device_name}")
        except Exception as e:
            log.warning(f"[ADB] Reconnect failed: {e}")

    def _adb_retry(self, *args, retries=3, delay=1.5, timeout=30, check=True):

        for attempt in range(retries):
            try:
                return self._adb(*args, timeout=timeout, check=check)
            except TimeoutExpired:
                log.warning(
                    f"[ADB] Screencap timed out (attempt {attempt + 1}/{retries}) "
                    f"for device {self.device_name}. Reconnecting..."
                )
                self._adb_reconnect()
                if attempt == retries - 1:
                    raise
                time.sleep(delay)
            except Exception:
                if attempt == retries - 1:
                    raise
                log.warning(f"ADB retry {attempt + 1}/{retries}")
                time.sleep(delay)

    # ─────────────────────────────────────────────
    # SCREENSHOT + ANALYSIS
    # ─────────────────────────────────────────────

    @keyword("Check Black Screen")
    def check_black_screen(
        self,
        filename: str = "screen.png",
        black_percentage_threshold: float = 95
    ) -> bool:

        local_path = os.path.join(self.screenshot_dir, filename)

        self.total_checks += 1

        log.info(f"[BLACK_SCREEN] Check #{self.total_checks}")

        try:
            # Small wait improves STB stability
            time.sleep(0.3)

            # Use _adb_retry so timeout triggers reconnect + retry
            log.debug(f"Taking screenshot for device: {self.device_name}")
            result = self._adb_retry("exec-out", "screencap", "-p", timeout=30, check=False)

            if result.returncode != 0:
                stderr_text = result.stderr.decode('utf-8', errors='replace') if result.stderr else 'None'
                stdout_text = result.stdout.decode('utf-8', errors='replace') if result.stdout else 'None' 
                log.error(
                    f"Screenshot capture failed:\n"
                    f"Return Code: {result.returncode}\n"
                    f"STDOUT: {stdout_text[:200]}{'...' if len(stdout_text) > 200 else ''}\n"
                    f"STDERR: {stderr_text[:200]}{'...' if len(stderr_text) > 200 else ''}"
                )
                raise RuntimeError(f"ADB screencap failed with return code {result.returncode}")

            if not result.stdout or len(result.stdout) < 1000:
                log.error(f"Screenshot data is too small: {len(result.stdout) if result.stdout else 0} bytes")
                raise RuntimeError("Screenshot data is invalid or too small")
            
            log.debug(f"Screenshot captured successfully: {len(result.stdout)} bytes")

            with open(local_path, "wb") as f:
                f.write(result.stdout)

            frame = cv2.imread(local_path)

            if frame is None:
                log.warning(f"Could not read screenshot: {local_path}")
                return True

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            black_pixels = np.sum(gray < 10)
            total_pixels = gray.size

            black_percentage = (black_pixels / total_pixels) * 100

            log.info(
                f"[BLACK_SCREEN] Black: {black_percentage:.1f}% "
                f"| Threshold: {black_percentage_threshold}%"
            )

            is_black = black_percentage >= black_percentage_threshold

            if is_black:

                self.consecutive_black_screens += 1
                self.black_screen_count += 1

                log.warning(
                    f"[BLACK_SCREEN] BLACK FRAME — "
                    f"{black_percentage:.1f}% black | "
                    f"Consecutive: {self.consecutive_black_screens}/"
                    f"{self.max_consecutive_allowed}"
                )

                if self.consecutive_black_screens >= self.max_consecutive_allowed:

                    msg = (
                        f"\nBLACK SCREEN FAILURE!\n"
                        f"Black pixels : {black_percentage:.1f}%\n"
                        f"Consecutive  : {self.consecutive_black_screens}\n"
                        f"Screenshot   : {local_path}"
                    )

                    log.error(msg)
                    raise AssertionError(msg)

            else:
                if self.consecutive_black_screens > 0:
                    log.info("[BLACK_SCREEN] Screen recovered")

                self.consecutive_black_screens = 0
                log.debug("[BLACK_SCREEN] Frame OK ✓")

            return True

        except AssertionError:
            raise

        except Exception as e:
            log.error(
                f"[BLACK_SCREEN] Unexpected error on check "
                f"#{self.total_checks}: {e}",
                exc_info=True
            )
            raise

    # ─────────────────────────────────────────────
    # STATISTICS / CONTROL
    # ─────────────────────────────────────────────

    @keyword("Get Black Screen Statistics")
    def get_black_screen_statistics(self) -> dict:

        stats = {
            "black screen count": self.black_screen_count,
            "total checks": self.total_checks,
            "consecutive black screens": self.consecutive_black_screens,
            "max consecutive allowed": self.max_consecutive_allowed,
        }

        log.debug(f"[BLACK_SCREEN] Stats: {stats}")

        return stats

    @keyword("Set Max Consecutive Black Screens")
    def set_max_consecutive_black_screens(self, count: int):

        self.max_consecutive_allowed = int(count)

        log.info(
            f"[BLACK_SCREEN] max_consecutive_allowed → "
            f"{self.max_consecutive_allowed}"
        )

    @keyword("Reset Black Screen Counter")
    def reset_black_screen_counter(self):

        self.consecutive_black_screens = 0
        self.total_checks = 0
        self.black_screen_count = 0

        log.info("[BLACK_SCREEN] Counters reset")

    @keyword("Check Black Screen From Bytes")
    def check_black_screen_from_bytes(
        self,
        screenshot_bytes: bytes,
        black_percentage_threshold: float = 95,
        save_path: str = None
    ) -> bool:
        """
        Analyze screenshot bytes for black screen without taking a new screenshot.
        
        Args:
            screenshot_bytes: PNG screenshot data as bytes
            black_percentage_threshold: Percentage threshold for black detection
            save_path: Optional path to save the screenshot for debugging
        
        Returns:
            bool: True if screen is NOT black, raises AssertionError if black
        """
        self.total_checks += 1
        log.info(f"[BLACK_SCREEN] Check #{self.total_checks} (from bytes)")

        try:
            # Decode bytes to numpy array
            nparr = np.frombuffer(screenshot_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame is None:
                log.warning("[BLACK_SCREEN] Could not decode screenshot bytes")
                return True

            # Optionally save for debugging
            if save_path:
                cv2.imwrite(save_path, frame)
                log.debug(f"[BLACK_SCREEN] Saved screenshot to {save_path}")

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            black_pixels = np.sum(gray < 10)
            total_pixels = gray.size

            black_percentage = (black_pixels / total_pixels) * 100

            log.info(
                f"[BLACK_SCREEN] Black: {black_percentage:.1f}% "
                f"| Threshold: {black_percentage_threshold}%"
            )

            is_black = black_percentage >= black_percentage_threshold

            if is_black:
                self.consecutive_black_screens += 1
                self.black_screen_count += 1

                log.warning(
                    f"[BLACK_SCREEN] BLACK FRAME — "
                    f"{black_percentage:.1f}% black | "
                    f"Consecutive: {self.consecutive_black_screens}/"
                    f"{self.max_consecutive_allowed}"
                )

                if self.consecutive_black_screens >= self.max_consecutive_allowed:
                    msg = (
                        f"\nBLACK SCREEN FAILURE!\n"
                        f"Black pixels : {black_percentage:.1f}%\n"
                        f"Consecutive  : {self.consecutive_black_screens}"
                    )
                    log.error(msg)
                    raise AssertionError(msg)
            else:
                if self.consecutive_black_screens > 0:
                    log.info("[BLACK_SCREEN] Screen recovered")
                self.consecutive_black_screens = 0
                log.debug("[BLACK_SCREEN] Frame OK ✓")

            return True

        except AssertionError:
            raise
        except Exception as e:
            log.error(
                f"[BLACK_SCREEN] Unexpected error on check "
                f"#{self.total_checks}: {e}",
                exc_info=True
            )
            raise

    @keyword("Set Screenshot Directory")
    def set_screenshot_directory(self, directory_path: str):

        self.screenshot_dir = directory_path
        os.makedirs(self.screenshot_dir, exist_ok=True)

        log.info(
            f"[BLACK_SCREEN] Screenshot directory → "
            f"{self.screenshot_dir}"
        )
