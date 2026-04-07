import pytest
import time
import os
import logging
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
log = logging.getLogger("TestBannerConfiguration")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Banner config from settings.yaml ───────────────────────────────────────
BN_CFG = SETTINGS.get("banner_configuration", {})
TATASKY_PACKAGE = BN_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
NAV_CFG = BN_CFG.get("navigation", {})
HOME_CFG = BN_CFG.get("home_check", {})
UI_IDS = BN_CFG.get("ui_ids", {})


class TestBannerConfiguration:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Banner Configuration test initialisation")

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

        # ── Logo compare ─────────────────────────────────────────────
        self.logo_compare = LogoCompareLibrary()

        # ── Appium session ───────────────────────────────────────────
        appium_url = os.getenv("APPIUM_URL", BN_CFG.get("appium_url", "http://localhost:4723"))
        self.driver = AppiumDriver.create(
            device_id=self.device_id,
            app_package=TATASKY_PACKAGE,
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
        """Navigate home and close Appium session"""
        log.info("CLEANUP — navigating home")
        try:
            self.device.home()
            time.sleep(2)
        except Exception as e:
            log.error(f"CLEANUP home() failed: {e}")
        try:
            AppiumDriver.quit(self.driver)
        except Exception as e:
            log.error(f"CLEANUP quit() failed: {e}")
        log.info("CLEANUP complete")

    def _take_step_screenshot(self, step_number, label=""):
        """Take a screenshot for the given step and return the saved path."""
        safe_label = label.replace(" ", "_").replace("/", "_")[:40]
        filename = f"banner_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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

    def test_banner_configuration(self, request):
        """
        Banner Configuration Setup — navigate to User Preferences →
        User Settings → Banner, verify/set banner duration to 10 seconds,
        then save and return home.

        Steps:
        1. Verify home screen
        2. Navigate UP 1, RIGHT 4, SELECT → User Preferences
        3. Verify User Preferences title
        4. Click User Settings button
        5. Select Banner menu item
        6. Verify banner duration is "10 seconds"; if not, click the
           next-value arrow until "10 seconds" appears
        7. Click Continue / Save button
        8. Press HOME
        """
        step_results = []
        status = "PASSED"
        error_message = ""
        current_step = 0

        home_logo_path = LOGO_DIR / HOME_CFG.get("logo_file", "Home.png")
        hc_region = HOME_CFG.get("region", [90, 120, 260, 180])
        hc_threshold = HOME_CFG.get("threshold", 0.60)
        hc_max = HOME_CFG.get("max_attempts", 4)

        # UI IDs
        user_settings_btn_id = UI_IDS.get("user_settings_btn", "tv.accedo.studio.paytv.tatasky:id/buttonUserSettings")
        title_id = UI_IDS.get("title", "tv.accedo.studio.paytv.tatasky:id/textViewTitle")
        banner_duration_id = UI_IDS.get("banner_duration", "tv.accedo.studio.paytv.tatasky:id/textView")
        continue_btn_id = UI_IDS.get("continue_btn", "tv.accedo.studio.paytv.tatasky:id/continuePictureSetting")

        # XPaths
        banner_menu_xpath = BN_CFG.get("xpaths", {}).get(
            "banner_menu",
            '//android.widget.CheckedTextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/menu_item" and @text="Banner"]'
        )

        target_duration = BN_CFG.get("target_duration_text", "10 seconds")
        banner_down_presses = BN_CFG.get("banner_down_presses", 1)
        max_right_presses = BN_CFG.get("max_right_presses", 20)

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
                         "Home screen logo confirmed",
                         "PASSED", ss1)

            # ─────────────────────────────────────────────────────────
            # STEP 2 — Navigate to User Preferences (UP 1, RIGHT 4, SELECT)
            # ─────────────────────────────────────────────────────────
            current_step = 2
            up_count = NAV_CFG.get("up_presses", 1)
            right_count = NAV_CFG.get("right_presses", 4)
            log.info(f"[STEP 2] Navigating UP {up_count}, RIGHT {right_count}, SELECT → User Preferences")
            for _ in range(up_count):
                self.device.up()
                time.sleep(0.3)
            self.device.navigate_right(right_count)
            time.sleep(0.5)
            self.device.select()
            time.sleep(3)
            ss2 = self._take_step_screenshot(2, "user_prefs_nav")
            _record_step(2, "Navigate to User Preferences",
                         f"Pressed UP {up_count}, RIGHT {right_count}, SELECT to open User Preferences",
                         "PASSED", ss2)

            # ─────────────────────────────────────────────────────────
            # STEP 3 — Verify User Preferences title
            # ─────────────────────────────────────────────────────────
            current_step = 3
            log.info("[STEP 3] Verifying User Preferences title…")
            title_text = self.ui.get_text_by_id(title_id, timeout=10)
            log.info(f"[STEP 3] Title text: '{title_text}'")
            ss3 = self._take_step_screenshot(3, "user_prefs_title")
            expected_title = BN_CFG.get("expected_user_prefs_title", "USER PREFERENCES")
            if expected_title.upper() not in title_text.upper():
                _record_step(3, "Verify User Preferences Title",
                             f"Expected '{expected_title}' but got '{title_text}'",
                             "FAILED", ss3, f"Got '{title_text}'")
                raise AssertionError(f"Expected '{expected_title}' in title but got '{title_text}'")
            log.info("[STEP 3] ✓ User Preferences screen confirmed")
            _record_step(3, "Verify User Preferences Title",
                         f"Title shows '{title_text}' — User Preferences screen confirmed",
                         "PASSED", ss3)

            # ─────────────────────────────────────────────────────────
            # STEP 4 — Click User Settings button
            # ─────────────────────────────────────────────────────────
            current_step = 4
            log.info(f"[STEP 4] Clicking User Settings button (id: {user_settings_btn_id})…")
            if not self.ui.exists_by_id(user_settings_btn_id, timeout=8):
                ss4 = self._take_step_screenshot(4, "user_settings_not_found")
                _record_step(4, "Click User Settings",
                             f"User Settings button (id: {user_settings_btn_id}) not found",
                             "FAILED", ss4, "User Settings button not found")
                raise AssertionError("User Settings button not found")
            self.ui.click_by_id(user_settings_btn_id, timeout=8)
            log.info("[STEP 4] ✓ Clicked User Settings button")
            time.sleep(3)
            ss4 = self._take_step_screenshot(4, "user_settings_clicked")
            _record_step(4, "Click User Settings",
                         f"Clicked User Settings button (id: {user_settings_btn_id})",
                         "PASSED", ss4)

            # ─────────────────────────────────────────────────────────
            # STEP 5 — Select Banner menu item
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Selecting Banner menu item…")
            if not self.ui.exists_by_xpath(banner_menu_xpath, timeout=8):
                ss5 = self._take_step_screenshot(5, "banner_menu_not_found")
                _record_step(5, "Select Banner Menu",
                             "Banner menu item not found in User Settings",
                             "FAILED", ss5, "Banner menu item not found")
                raise AssertionError("Banner menu item not found in User Settings")
            self.ui.click_by_xpath(banner_menu_xpath, timeout=8)
            log.info("[STEP 5] ✓ Clicked Banner menu item")
            time.sleep(2)
            ss5 = self._take_step_screenshot(5, "banner_selected")
            _record_step(5, "Select Banner Menu",
                         "Clicked Banner menu item in User Settings",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Press DOWN to duration selector, then RIGHT until target
            # ─────────────────────────────────────────────────────────
            current_step = 6
            log.info(f"[STEP 6] Pressing DOWN {banner_down_presses} to reach duration selector…")
            for _ in range(banner_down_presses):
                self.device.navigate_down()
                time.sleep(0.4)

            log.info(f"[STEP 6] Checking banner duration — target: '{target_duration}'…")
            current_duration = ""
            duration_matched = False
            rights_used = 0

            for right_attempt in range(max_right_presses + 1):
                # Read current value
                try:
                    current_duration = self.ui.get_text_by_id(banner_duration_id, timeout=5)
                except Exception:
                    current_duration = ""
                log.info(f"[STEP 6] Banner duration text: '{current_duration}' (attempt {right_attempt})")

                if target_duration.lower() in current_duration.lower():
                    duration_matched = True
                    rights_used = right_attempt
                    log.info(f"[STEP 6] ✓ Target duration '{target_duration}' reached after {right_attempt} RIGHT press(es)")
                    break

                if right_attempt < max_right_presses:
                    self.device.navigate_right(1)
                    time.sleep(0.5)

            ss6 = self._take_step_screenshot(6, "banner_duration")
            if not duration_matched:
                _record_step(6, "Set Banner Duration",
                             f"Could not set banner duration to '{target_duration}' after "
                             f"{max_right_presses} RIGHT press(es). Last value: '{current_duration}'",
                             "FAILED", ss6,
                             f"Banner duration '{target_duration}' not reached. Got: '{current_duration}'")
                raise AssertionError(
                    f"Banner duration '{target_duration}' not reached after "
                    f"{max_right_presses} RIGHT presses. Last value: '{current_duration}'"
                )
            _record_step(6, "Set Banner Duration",
                         f"Banner duration confirmed as '{current_duration}' "
                         f"(DOWN {banner_down_presses}, then {rights_used} RIGHT press(es))",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Click Continue / Save button
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info(f"[STEP 7] Clicking Continue button (id: {continue_btn_id})…")
            if not self.ui.exists_by_id(continue_btn_id, timeout=8):
                ss7 = self._take_step_screenshot(7, "continue_not_found")
                _record_step(7, "Click Continue / Save",
                             f"Continue button (id: {continue_btn_id}) not found",
                             "FAILED", ss7, "Continue button not found")
                raise AssertionError("Continue / Save button not found")
            self.ui.click_by_id(continue_btn_id, timeout=8)
            log.info("[STEP 7] ✓ Clicked Continue button — banner duration saved")
            time.sleep(2)
            ss7 = self._take_step_screenshot(7, "continue_clicked")
            _record_step(7, "Click Continue / Save",
                         f"Clicked Continue button (id: {continue_btn_id}) — settings saved",
                         "PASSED", ss7)

            # ─────────────────────────────────────────────────────────
            # STEP 8 — Press HOME
            # ─────────────────────────────────────────────────────────
            current_step = 8
            log.info("[STEP 8] Pressing HOME…")
            self.device.home()
            time.sleep(2)
            ss8 = self._take_step_screenshot(8, "home")
            _record_step(8, "Return to Home",
                         "Pressed HOME to return to home screen",
                         "PASSED", ss8)

        except Exception as e:
            if not error_message:
                status = "FAILED"
                error_message = str(e)
            log.error(f"TEST FAILED at step {current_step}: {e}", exc_info=True)

            # Mark remaining steps as SKIPPED
            recorded_nums = {s["step_number"] for s in step_results}
            all_step_names = {
                1: "Verify Home Screen",
                2: "Navigate to User Preferences",
                3: "Verify User Preferences Title",
                4: "Click User Settings",
                5: "Select Banner Menu",
                6: "Set Banner Duration",
                7: "Click Continue / Save",
                8: "Return to Home",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_banner_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:
            self.report_gen.add_module_report(
                module_name="Banner Configuration Setup",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
            )
            log.info(f"[RESULT] Status={status}")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)
