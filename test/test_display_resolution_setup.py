import pytest
import time
import os
import logging
import traceback
from pathlib import Path
import yaml

from core.device_manager import DeviceManager
from core.report_manager import ReportGenerator
from libraries.DeviceController import DeviceController
from libraries.appium_utils import AppiumDriver, AppiumHelper
from libraries.LogoCompareLibrary import LogoCompareLibrary

# ─── Logger setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("TestDisplayResolutionSetup")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Display Resolution config from settings.yaml ───────────────────────────
DR_CFG = SETTINGS.get("display_resolution", {})
NAV_CFG = DR_CFG.get("navigation", {})
HOME_CFG = DR_CFG.get("home_check", {})
UI_IDS = DR_CFG.get("ui_ids", {})
EXPECTED = DR_CFG.get("expected_texts", {})
XPATHS = DR_CFG.get("xpaths", {})


class TestDisplayResolutionSetup:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Display Resolution Setup test initialisation")

        # ── Resolve device ID ────────────────────────────────────────
        self.device_id = (
            os.getenv("DEVICE_ID")
            or os.getenv("DEVICE_NAME")
            or os.getenv("TARGET_DEVICE")
        )
        if not self.device_id:
            log.warning("No DEVICE_ID env var — falling back to first connected device")
            self.device_id = DeviceManager.get_connected_devices()[0]

        log.info(f"Using device: {self.device_id}")

        # ── ADB device controller ────────────────────────────────────
        self.device = DeviceController(self.device_id)

        # ── Logo compare (for home screen check) ────────────────────
        self.logo_compare = LogoCompareLibrary()

        # ── Appium session (no app package — navigating via Settings) ─
        appium_url = os.getenv("APPIUM_URL", DR_CFG.get("appium_url", "http://localhost:4723"))
        self.driver = AppiumDriver.create(
            device_id=self.device_id,
            app_package="",
            appium_url=appium_url,
        )
        self.ui = AppiumHelper(self.driver, default_timeout=10)
        log.info("Appium session created")

        # ── Report generator ─────────────────────────────────────────
        self.report_gen = ReportGenerator(request.node.execution_dir)
        self.screenshots_folder = request.node.screenshot_dir

        log.info("SETUP complete")
        yield
        self._cleanup()

    def _cleanup(self):
        """Close Appium session (no home press — device may be rebooting)"""
        log.info("CLEANUP — closing Appium session")
        try:
            AppiumDriver.quit(self.driver)
        except Exception as e:
            log.error(f"CLEANUP quit() failed: {e}")
        log.info("CLEANUP complete")

    def _take_step_screenshot(self, step_number, label=""):
        """Take a screenshot for the given step and return the saved path."""
        safe_label = label.replace(" ", "_").replace("/", "_")[:40]
        filename = f"disp_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
        save_path = self.screenshots_folder / filename
        try:
            self.device.take_screenshot(str(save_path))
        except Exception as e:
            log.warning(f"[SCREENSHOT] Step {step_number} failed: {e}")
            return None
        return str(save_path)

    # ══════════════════════════════════════════════════════════════════
    #  MAIN TEST
    # ══════════════════════════════════════════════════════════════════

    def test_display_resolution_setup(self, request):
        """
        Display Resolution Setup — navigate to Android TV Settings →
        Device Preferences → Display → Resolution, select the target
        resolution option, then wait for the device to reboot and
        return to the home screen.

        Steps:
        1.  Verify home screen
        2.  Navigate UP 1, RIGHT 3, SELECT → Android TV Settings
        3.  Verify "Settings" title
        4.  Click "Device Preferences"
        5.  Verify "Device Preferences" title
        6.  Click Display menu item (LinearLayout[6])
        7.  Verify "Display" title
        8.  Click Resolution option (LinearLayout[1])
        9.  Select resolution container (container)[2]
        10. Confirm resolution selection (guidedactions_list LinearLayout[2])
        11. Wait 60 s for device reboot
        12. Press HOME until home screen detected
        """
        step_results = []
        status = "PASSED"
        error_message = ""
        current_step = 0

        home_logo_path = LOGO_DIR / HOME_CFG.get("logo_file", "Home.png")
        hc_region = HOME_CFG.get("region", [90, 120, 260, 180])
        hc_threshold = HOME_CFG.get("threshold", 0.60)
        hc_max = HOME_CFG.get("max_attempts", 4)

        def _record_step(num, name, desc, st, ss_path=None, err=""):
            step_results.append({
                "step_number": num,
                "step_name": name,
                "description": desc,
                "status": st,
                "screenshot": ss_path,
                "error_message": err,
            })

        try:
            # ─────────────────────────────────────────────────────────
            # STEP 1 — Verify home screen
            # ─────────────────────────────────────────────────────────
            current_step = 1
            log.info("[STEP 1] Checking home screen…")
            home_detected = False
            for attempt in range(1, hc_max + 1):
                screenshot_bytes = self.device.take_screenshot_bytes()
                try:
                    self.logo_compare.fail_if_logo_not_present_bytes(
                        screenshot_bytes, str(home_logo_path),
                        x=hc_region[0], y=hc_region[1],
                        width=hc_region[2], height=hc_region[3],
                        threshold=hc_threshold,
                    )
                    log.info(f"[STEP 1] Home screen detected (attempt {attempt})")
                    home_detected = True
                    break
                except AssertionError:
                    log.warning(f"[STEP 1] Home not detected (attempt {attempt}/{hc_max}), pressing HOME…")
                    self.device.home()
                    time.sleep(2)

            ss1 = self._take_step_screenshot(1, "home_screen")
            if not home_detected:
                _record_step(1, "Verify Home Screen",
                             f"Home logo not detected after {hc_max} attempts",
                             "FAILED", ss1,
                             f"Home screen not detected after {hc_max} attempts")
                raise AssertionError(f"Home screen not detected after {hc_max} attempts")
            _record_step(1, "Verify Home Screen",
                         "Home screen logo confirmed — device is on home screen",
                         "PASSED", ss1)

            # ─────────────────────────────────────────────────────────
            # STEP 2 — Navigate to Android TV Settings (UP 1, RIGHT 3, SELECT)
            # ─────────────────────────────────────────────────────────
            current_step = 2
            up_count = NAV_CFG.get("up_presses", 1)
            right_count = NAV_CFG.get("right_presses", 3)
            log.info(f"[STEP 2] Navigating UP {up_count}, RIGHT {right_count}, SELECT → Android TV Settings")
            for _ in range(up_count):
                self.device.up()
                time.sleep(0.3)
            self.device.navigate_right(right_count)
            time.sleep(0.5)
            self.device.select()
            time.sleep(3)
            ss2 = self._take_step_screenshot(2, "android_settings_nav")
            _record_step(2, "Navigate to Android TV Settings",
                         f"Pressed UP {up_count}, RIGHT {right_count}, SELECT to open Android TV Settings",
                         "PASSED", ss2)

            # ─────────────────────────────────────────────────────────
            # STEP 3 — Verify "Settings" title
            # ─────────────────────────────────────────────────────────
            current_step = 3
            log.info("[STEP 3] Verifying Settings title…")
            settings_title_id = UI_IDS.get("settings_title", "com.android.tv.settings:id/decor_title")
            expected_settings = EXPECTED.get("settings", "Settings")
            title_text = self.ui.get_text_by_id(settings_title_id, timeout=10)
            log.info(f"[STEP 3] Title text: '{title_text}'")
            ss3 = self._take_step_screenshot(3, "settings_title")
            if expected_settings.upper() not in title_text.upper():
                _record_step(3, "Verify Settings Title",
                             f"Expected '{expected_settings}' but got '{title_text}'",
                             "FAILED", ss3, f"Got '{title_text}'")
                raise AssertionError(f"Expected '{expected_settings}' in title but got '{title_text}'")
            log.info("[STEP 3] ✓ Settings screen confirmed")
            _record_step(3, "Verify Settings Title",
                         f"Title shows '{title_text}' — Settings screen confirmed",
                         "PASSED", ss3)

            # ─────────────────────────────────────────────────────────
            # STEP 4 — Click "Device Preferences"
            # ─────────────────────────────────────────────────────────
            current_step = 4
            log.info("[STEP 4] Clicking 'Device Preferences'…")
            device_prefs_xpath = XPATHS.get(
                "device_preferences",
                '//android.widget.TextView[@resource-id="android:id/title" and @text="Device Preferences"]'
            )
            if not self.ui.exists_by_xpath(device_prefs_xpath, timeout=8):
                ss4 = self._take_step_screenshot(4, "device_prefs_not_found")
                _record_step(4, "Click Device Preferences",
                             "'Device Preferences' not found on Settings screen",
                             "FAILED", ss4, "'Device Preferences' menu item not found")
                raise AssertionError("'Device Preferences' menu item not found")
            self.ui.click_by_xpath(device_prefs_xpath, timeout=8)
            log.info("[STEP 4] ✓ Clicked 'Device Preferences'")
            time.sleep(3)
            ss4 = self._take_step_screenshot(4, "device_prefs_clicked")
            _record_step(4, "Click Device Preferences",
                         "Found and clicked 'Device Preferences'",
                         "PASSED", ss4)

            # ─────────────────────────────────────────────────────────
            # STEP 5 — Verify "Device Preferences" title
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Verifying 'Device Preferences' title…")
            expected_device_prefs = EXPECTED.get("device_preferences", "Device Preferences")
            decor_text = self.ui.get_text_by_id(settings_title_id, timeout=10)
            log.info(f"[STEP 5] Decor title text: '{decor_text}'")
            ss5 = self._take_step_screenshot(5, "device_prefs_title")
            if expected_device_prefs.upper() not in decor_text.upper():
                _record_step(5, "Verify Device Preferences Title",
                             f"Expected '{expected_device_prefs}' but got '{decor_text}'",
                             "FAILED", ss5, f"Got '{decor_text}'")
                raise AssertionError(f"Expected '{expected_device_prefs}' in title but got '{decor_text}'")
            log.info("[STEP 5] ✓ Device Preferences screen confirmed")
            _record_step(5, "Verify Device Preferences Title",
                         f"Title shows '{decor_text}' — Device Preferences screen confirmed",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Navigate to Display (DOWN ×10, SELECT)
            # ─────────────────────────────────────────────────────────
            current_step = 6
            down_count = DR_CFG.get("display_down_presses", 11)
            log.info(f"[STEP 6] Pressing DOWN {down_count} times then SELECT to navigate to Display…")
            self.device.navigate_down(down_count)
            time.sleep(0.5)
            self.device.select()
            time.sleep(3)
            ss6 = self._take_step_screenshot(6, "display_clicked")
            _record_step(6, "Navigate to Display",
                         f"Pressed DOWN {down_count} times then SELECT to open Display settings",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Verify "Display" title
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info("[STEP 7] Verifying 'Display' title…")
            display_title_id = UI_IDS.get(
                "display_title",
                "com.technicolor.tv.settings.device.display:id/decor_title"
            )
            expected_display = EXPECTED.get("display", "Display")
            display_title_text = self.ui.get_text_by_id(display_title_id, timeout=10)
            log.info(f"[STEP 7] Display title text: '{display_title_text}'")
            ss7 = self._take_step_screenshot(7, "display_title")
            if expected_display.upper() not in display_title_text.upper():
                _record_step(7, "Verify Display Title",
                             f"Expected '{expected_display}' but got '{display_title_text}'",
                             "FAILED", ss7, f"Got '{display_title_text}'")
                raise AssertionError(f"Expected '{expected_display}' in title but got '{display_title_text}'")
            log.info("[STEP 7] ✓ Display screen confirmed")
            _record_step(7, "Verify Display Title",
                         f"Title shows '{display_title_text}' — Display screen confirmed",
                         "PASSED", ss7)

            # ─────────────────────────────────────────────────────────
            # STEP 8 — Click Resolution option (LinearLayout[1])
            # ─────────────────────────────────────────────────────────
            current_step = 8
            log.info("[STEP 8] Clicking Resolution option…")
            resolution_option_xpath = XPATHS.get(
                "resolution_option",
                '//androidx.recyclerview.widget.RecyclerView[@resource-id="com.technicolor.tv.settings.device.display:id/list"]/android.widget.LinearLayout[1]'
            )
            if not self.ui.exists_by_xpath(resolution_option_xpath, timeout=8):
                ss8 = self._take_step_screenshot(8, "resolution_option_not_found")
                _record_step(8, "Click Resolution Option",
                             "Resolution option (LinearLayout[1]) not found in Display list",
                             "FAILED", ss8, "Resolution option not found")
                raise AssertionError("Resolution option not found in Display list")
            self.ui.click_by_xpath(resolution_option_xpath, timeout=8)
            log.info("[STEP 8] ✓ Clicked Resolution option")
            time.sleep(3)
            ss8 = self._take_step_screenshot(8, "resolution_option_clicked")
            _record_step(8, "Click Resolution Option",
                         "Clicked Resolution option (LinearLayout[1]) from Display list",
                         "PASSED", ss8)

            # ─────────────────────────────────────────────────────────
            # STEP 9 — Select resolution container [2]
            # ─────────────────────────────────────────────────────────
            current_step = 9
            log.info("[STEP 9] Selecting resolution container [2]…")
            resolution_container_xpath = XPATHS.get(
                "resolution_container",
                '(//android.widget.LinearLayout[@resource-id="com.technicolor.tv.settings.device.display:id/container"])[2]'
            )
            if not self.ui.exists_by_xpath(resolution_container_xpath, timeout=8):
                ss9 = self._take_step_screenshot(9, "resolution_container_not_found")
                _record_step(9, "Select Resolution Container",
                             "Resolution container [2] not found",
                             "FAILED", ss9, "Resolution container [2] not found")
                raise AssertionError("Resolution container [2] not found")
            self.ui.click_by_xpath(resolution_container_xpath, timeout=8)
            log.info("[STEP 9] ✓ Selected resolution container [2]")
            time.sleep(2)
            ss9 = self._take_step_screenshot(9, "resolution_container_selected")
            _record_step(9, "Select Resolution Container",
                         "Clicked resolution container [2] to select the resolution option",
                         "PASSED", ss9)

            # ─────────────────────────────────────────────────────────
            # STEP 10 — Confirm resolution (guidedactions_list LinearLayout[2])
            # ─────────────────────────────────────────────────────────
            current_step = 10
            log.info("[STEP 10] Confirming resolution selection…")
            confirm_xpath = XPATHS.get(
                "resolution_confirm",
                '//androidx.recyclerview.widget.RecyclerView[@resource-id="com.technicolor.tv.settings.device.display:id/guidedactions_list"]/android.widget.LinearLayout[2]'
            )
            if not self.ui.exists_by_xpath(confirm_xpath, timeout=8):
                ss10 = self._take_step_screenshot(10, "confirm_not_found")
                _record_step(10, "Confirm Resolution Selection",
                             "Confirm button (guidedactions_list LinearLayout[2]) not found",
                             "FAILED", ss10, "Resolution confirm button not found")
                raise AssertionError("Resolution confirm button not found in guided actions")
            self.ui.click_by_xpath(confirm_xpath, timeout=8)
            log.info("[STEP 10] ✓ Confirmed resolution selection")
            ss10 = self._take_step_screenshot(10, "resolution_confirmed")
            _record_step(10, "Confirm Resolution Selection",
                         "Clicked confirm (guidedactions_list LinearLayout[2]) — resolution applied",
                         "PASSED", ss10)

            # ─────────────────────────────────────────────────────────
            # STEP 11 — Wait 60 s for device reboot
            # ─────────────────────────────────────────────────────────
            current_step = 11
            reboot_wait = DR_CFG.get("reboot_wait_seconds", 60)
            log.info(f"[STEP 11] Waiting {reboot_wait}s for device to reboot after resolution change…")
            time.sleep(reboot_wait)
            _record_step(11, "Wait for Device Reboot",
                         f"Waited {reboot_wait}s for device to reboot after resolution change",
                         "PASSED", None)

            # ─────────────────────────────────────────────────────────
            # STEP 12 — Press HOME until home screen detected
            # ─────────────────────────────────────────────────────────
            current_step = 12
            log.info("[STEP 12] Pressing HOME until home screen is detected…")
            max_home_presses = DR_CFG.get("max_home_presses", 15)
            home_after_reboot = False
            for attempt in range(1, max_home_presses + 1):
                self.device.home()
                time.sleep(3)
                try:
                    screenshot_bytes = self.device.take_screenshot_bytes()
                    self.logo_compare.fail_if_logo_not_present_bytes(
                        screenshot_bytes, str(home_logo_path),
                        x=hc_region[0], y=hc_region[1],
                        width=hc_region[2], height=hc_region[3],
                        threshold=hc_threshold,
                    )
                    log.info(f"[STEP 12] Home screen detected after {attempt} HOME press(es)")
                    home_after_reboot = True
                    break
                except AssertionError:
                    log.info(f"[STEP 12] HOME press {attempt}/{max_home_presses} — not at home yet")
                except Exception as e:
                    log.warning(f"[STEP 12] HOME press {attempt}/{max_home_presses} — screenshot failed: {e}")

            ss12 = self._take_step_screenshot(12, "home_after_reboot")
            if not home_after_reboot:
                log.warning(f"[STEP 12] Home not detected after {max_home_presses} attempts — marking as WARNING")
                _record_step(12, "Return to Home After Reboot",
                             f"Home screen not detected after {max_home_presses} HOME press attempts",
                             "FAILED", ss12,
                             f"Home screen not detected after {max_home_presses} HOME presses post-reboot")
                status = "FAILED"
                error_message = f"HOME screen not restored after {max_home_presses} attempts following reboot"
            else:
                _record_step(12, "Return to Home After Reboot",
                             f"Home screen detected after {attempt} HOME press(es) — test complete",
                             "PASSED", ss12)

        except Exception as e:
            if not error_message:
                status = "FAILED"
                error_message = str(e)
            log.error(f"TEST FAILED at step {current_step}: {e}", exc_info=True)

            # Mark remaining steps as SKIPPED
            recorded_nums = {s["step_number"] for s in step_results}
            all_step_names = {
                1: "Verify Home Screen",
                2: "Navigate to Android TV Settings",
                3: "Verify Settings Title",
                4: "Click Device Preferences",
                5: "Verify Device Preferences Title",
                6: "Click Display Menu Item",
                7: "Verify Display Title",
                8: "Click Resolution Option",
                9: "Select Resolution Container",
                10: "Confirm Resolution Selection",
                11: "Wait for Device Reboot",
                12: "Return to Home After Reboot",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_display_resolution_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:
            # ── Module-wise step-by-step Excel sheet ──────────────────
            self.report_gen.add_module_report(
                module_name="Display Resolution Setup",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
            )

            log.info(f"[RESULT] Status={status}")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)
