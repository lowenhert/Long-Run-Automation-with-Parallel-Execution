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
from libraries.navigation_cleanup import navigate_back_until_home

# ─── Logger setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("TestLNBSettings")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── LNB Settings config from settings.yaml ─────────────────────────────────
LNB_CFG = SETTINGS.get("lnb_settings", {})
TATASKY_PACKAGE = LNB_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
NAV_CFG = LNB_CFG.get("navigation", {})
HOME_CFG = LNB_CFG.get("home_check", {})
UI_IDS = LNB_CFG.get("ui_ids", {})
LNB_TYPE = LNB_CFG.get("lnb_type", "Super LNB")
FREQUENCY = LNB_CFG.get("frequency", "11.222")
POLARIZATION = LNB_CFG.get("polarization", "HORIZONTAL")
SYMBOL_RATE = LNB_CFG.get("symbol_rate", "32.721")
MAX_CLICK_ATTEMPTS = LNB_CFG.get("max_click_attempts", 20)
SIGNAL_CHECK_CHANNEL = LNB_CFG.get("signal_check_channel", "455")
SIGNAL_STRENGTH_MIN = LNB_CFG.get("signal_strength_min", 10)


def _parse_digits(value_str):
    """Parse a frequency/symbol-rate string like '11.222' into individual digits, ignoring the dot."""
    return [ch for ch in value_str if ch.isdigit()]


class TestLNBSettings:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — LNB Settings test initialisation")

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

        # ── ADB device controller (for key events) ──────────────────
        self.device = DeviceController(self.device_id)

        # ── Logo compare (for home screen check) ────────────────────
        self.logo_compare = LogoCompareLibrary()

        # ── Appium session (for UI element interaction) ──────────────
        appium_url = os.getenv("APPIUM_URL", LNB_CFG.get("appium_url", "http://localhost:4723"))
        self.driver = AppiumDriver.create(
            device_id=self.device_id,
            app_package=TATASKY_PACKAGE,
            appium_url=appium_url,
        )
        self.ui = AppiumHelper(self.driver, default_timeout=15)
        log.info("Appium session created")

        # ── Report generator ─────────────────────────────────────────
        self.report_gen = ReportGenerator(request.node.execution_dir)
        self.screenshots_folder = request.node.screenshot_dir

        log.info("SETUP complete")
        yield
        self._cleanup()

    def _cleanup(self):
        """Navigate back/home and close Appium session"""
        log.info("CLEANUP — pressing HOME to return to home screen")
        try:
            home_logo_path = LOGO_DIR / HOME_CFG.get("logo_file", "Home.png")
            navigate_back_until_home(
                device=self.device,
                logo_compare=self.logo_compare,
                home_logo_path=home_logo_path,
                home_region=HOME_CFG.get("region", [90, 120, 260, 180]),
                home_threshold=HOME_CFG.get("threshold", 0.60),
                max_back_presses=0,
                max_home_presses=HOME_CFG.get("max_home_presses", 4),
                settle_seconds=HOME_CFG.get("cleanup_settle_seconds", 1.0),
                logger=log,
            )
        except Exception as e:
            log.error(f"CLEANUP navigation failed: {e}")
        try:
            AppiumDriver.quit(self.driver)
        except Exception as e:
            log.error(f"CLEANUP quit() failed: {e}")
        log.info("CLEANUP complete")

    def _take_step_screenshot(self, step_number, label=""):
        """Take a screenshot for the given step and return the saved path."""
        safe_label = label.replace(" ", "_").replace("/", "_")[:40]
        filename = f"lnb_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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

    def test_lnb_settings(self, request):
        """
        LNB Settings Setup — navigate to Satellite Settings → LNB Settings,
        select LNB type, configure transponder frequency, polarization, and
        symbol rate.

        Steps:
         1. Verify Home screen
         2. Navigate to User Preferences (UP + RIGHT + SELECT)
         3. Verify USER PREFERENCES title
         4. Click System Settings button
         5. Enter PIN 01 and verify Satellite Settings text
         6. Click Launch Satellite Settings and verify LNB Settings text
         7. Click ImageView until LNB type matches config (e.g. Super LNB)
         8. Click Next button
         9. Click Edit button (editable ImageView)
        10. Click Select and verify Transponder setup screen
        11. Enter Frequency digits
        12. Set Polarization
        13. Enter Symbol Rate digits
        14. Click Select button to confirm
        """
        step_results = []
        status = "PASSED"
        error_message = ""
        current_step = 0

        TOTAL_STEPS = 19

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
            # STEP 1 — Verify we are on the Home screen
            # ─────────────────────────────────────────────────────────
            current_step = 1
            log.info("[STEP 1] Checking home screen…")
            home_logo_path = LOGO_DIR / HOME_CFG.get("logo_file", "Home.png")
            hc_region = HOME_CFG.get("region", [90, 120, 260, 180])
            hc_threshold = HOME_CFG.get("threshold", 0.60)
            hc_max = HOME_CFG.get("max_attempts", 4)
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
                    time.sleep(3)

            ss1 = self._take_step_screenshot(1, "home_screen")
            if not home_detected:
                _record_step(1, "Verify Home Screen",
                             f"Home logo not detected after {hc_max} attempts",
                             "FAILED", ss1,
                             f"Home screen not detected after {hc_max} attempts")
                raise AssertionError(f"Home screen not detected after {hc_max} attempts")
            _record_step(1, "Verify Home Screen",
                         "Checked home screen logo — confirmed home is visible",
                         "PASSED", ss1)

            # ─────────────────────────────────────────────────────────
            # STEP 2 — Navigate to User Preferences (UP + RIGHT + SELECT)
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
            time.sleep(5)
            ss2 = self._take_step_screenshot(2, "user_preferences_nav")
            _record_step(2, "Navigate to User Preferences",
                         f"Pressed UP {up_count}, RIGHT {right_count}, SELECT to open User Preferences",
                         "PASSED", ss2)

            # ─────────────────────────────────────────────────────────
            # STEP 3 — Verify USER PREFERENCES title
            # ─────────────────────────────────────────────────────────
            current_step = 3
            log.info("[STEP 3] Verifying USER PREFERENCES title…")
            title_id = UI_IDS.get("title", "textViewTitle")
            title_text = self.ui.get_text_by_id(
                f"{TATASKY_PACKAGE}:id/{title_id}", timeout=15
            )
            log.info(f"[STEP 3] Title text: '{title_text}'")
            ss3 = self._take_step_screenshot(3, "user_pref_title")
            if "USER PREFERENCES" not in title_text.upper():
                _record_step(3, "Verify USER PREFERENCES Title",
                             f"Expected 'USER PREFERENCES' but got '{title_text}'",
                             "FAILED", ss3, f"Got '{title_text}'")
                raise AssertionError(
                    f"Expected 'USER PREFERENCES' but got '{title_text}'"
                )
            log.info("[STEP 3] ✓ USER PREFERENCES screen confirmed")
            _record_step(3, "Verify USER PREFERENCES Title",
                         f"Title shows '{title_text}' — screen confirmed",
                         "PASSED", ss3)

            # ─────────────────────────────────────────────────────────
            # STEP 4 — Click System Settings button
            # ─────────────────────────────────────────────────────────
            current_step = 4
            log.info("[STEP 4] Clicking System Settings button…")
            system_btn = UI_IDS.get("system_settings_btn", "buttonSystemSettings")
            system_btn_id = f"{TATASKY_PACKAGE}:id/{system_btn}"
            self.ui.click_by_id(system_btn_id, timeout=15)
            time.sleep(5)
            ss4 = self._take_step_screenshot(4, "system_settings_clicked")
            log.info("[STEP 4] ✓ System Settings button clicked")
            _record_step(4, "Click System Settings",
                         "Clicked System Settings button",
                         "PASSED", ss4)

            # ─────────────────────────────────────────────────────────
            # STEP 5 — Press 01 and verify Satellite Settings
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Pressing numeric keys 0 then 1, then SELECT…")
            self.ui.press_keycode(7)   # KEYCODE_0
            time.sleep(0.5)
            self.ui.press_keycode(8)   # KEYCODE_1
            time.sleep(0.5)
            self.device.select()
            time.sleep(5)

            # Verify "Satellite Settings" text is on screen
            sat_selector = 'new UiSelector().text("Satellite Settings")'
            sat_el = self.ui.find_by_uiautomator(sat_selector, timeout=15)
            ss5 = self._take_step_screenshot(5, "satellite_settings_visible")
            if sat_el is None:
                _record_step(5, "Verify Satellite Settings",
                             "Satellite Settings text not found on screen",
                             "FAILED", ss5, "Satellite Settings not found")
                raise AssertionError("Satellite Settings text not found")
            log.info("[STEP 5] ✓ Satellite Settings text found")
            _record_step(5, "Verify Satellite Settings",
                         "Pressed 01 and verified Satellite Settings on screen",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Click Launch Satellite Settings and verify LNB Settings
            # ─────────────────────────────────────────────────────────
            current_step = 6
            log.info("[STEP 6] Clicking Launch Satellite Settings…")
            launch_sat = UI_IDS.get("launch_satellite_settings", "launchSatelliteSettings")
            launch_sat_id = f"{TATASKY_PACKAGE}:id/{launch_sat}"
            self.ui.click_by_id(launch_sat_id, timeout=15)
            time.sleep(5)

            # Verify "LNB Settings" text is on screen
            lnb_selector = 'new UiSelector().text("LNB Settings")'
            lnb_el = self.ui.find_by_uiautomator(lnb_selector, timeout=15)
            ss6 = self._take_step_screenshot(6, "lnb_settings_visible")
            if lnb_el is None:
                _record_step(6, "Verify LNB Settings",
                             "LNB Settings text not found on screen",
                             "FAILED", ss6, "LNB Settings not found")
                raise AssertionError("LNB Settings text not found")
            log.info("[STEP 6] ✓ LNB Settings text found")
            _record_step(6, "Verify LNB Settings",
                         "Clicked Launch Satellite Settings and verified LNB Settings on screen",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Click ImageView(2) until LNB type matches config
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info(f"[STEP 7] Clicking ImageView until LNB type = '{LNB_TYPE}'…")
            text_view_id = f"{TATASKY_PACKAGE}:id/{UI_IDS.get('text_view', 'textView')}"
            img_selector = 'new UiSelector().className("android.widget.ImageView").instance(2)'

            found_lnb = False
            for attempt in range(1, MAX_CLICK_ATTEMPTS + 1):
                current_text = self.ui.get_text_by_id(text_view_id, timeout=12)
                log.info(f"[STEP 7] Attempt {attempt}: current LNB type = '{current_text}'")
                if current_text.strip() == LNB_TYPE:
                    found_lnb = True
                    break
                # Click the ImageView to cycle to next option
                img_el = self.ui.find_by_uiautomator(img_selector, timeout=12)
                img_el.click()
                time.sleep(2)

            ss7 = self._take_step_screenshot(7, "lnb_type_selected")
            if not found_lnb:
                _record_step(7, "Select LNB Type",
                             f"LNB type '{LNB_TYPE}' not found after {MAX_CLICK_ATTEMPTS} attempts",
                             "FAILED", ss7,
                             f"LNB type '{LNB_TYPE}' not found")
                raise AssertionError(f"LNB type '{LNB_TYPE}' not found after {MAX_CLICK_ATTEMPTS} attempts")
            log.info(f"[STEP 7] ✓ LNB type set to '{LNB_TYPE}'")
            _record_step(7, "Select LNB Type",
                         f"Cycled through options until LNB type = '{LNB_TYPE}'",
                         "PASSED", ss7)

            # ─────────────────────────────────────────────────────────
            # STEP 8 — Click Next button
            # ─────────────────────────────────────────────────────────
            current_step = 8
            log.info("[STEP 8] Clicking Next button…")
            next_btn = UI_IDS.get("next_button", "next_button")
            next_btn_id = f"{TATASKY_PACKAGE}:id/{next_btn}"
            self.ui.click_by_id(next_btn_id, timeout=15)
            time.sleep(5)
            ss8 = self._take_step_screenshot(8, "next_clicked")
            log.info("[STEP 8] ✓ Next button clicked")
            _record_step(8, "Click Next Button",
                         "Clicked Next button to proceed",
                         "PASSED", ss8)

            # ─────────────────────────────────────────────────────────
            # STEP 9 — Click Edit button (editable ImageView)
            # ─────────────────────────────────────────────────────────
            current_step = 9
            log.info("[STEP 9] Clicking Edit (editable) button…")
            editable_id = f"{TATASKY_PACKAGE}:id/{UI_IDS.get('editable', 'editable')}"
            self.ui.click_by_id(editable_id, timeout=15)
            time.sleep(5)
            ss9 = self._take_step_screenshot(9, "edit_clicked")
            log.info("[STEP 9] ✓ Edit button clicked")
            _record_step(9, "Click Edit Button",
                         "Clicked Edit (editable) button",
                         "PASSED", ss9)

            # ─────────────────────────────────────────────────────────
            # STEP 10 — Verify Transponder setup screen
            # ─────────────────────────────────────────────────────────
            current_step = 10
            log.info("[STEP 10] Verifying Transponder setup screen…")
            # Edit button causes activity transition — give UiAutomator2 time to recover
            time.sleep(7)

            transponder_selector = 'new UiSelector().text("Transponder setup")'
            transponder_el = None

            # Retry strategies: first wait, then SELECT, then re-click Edit + SELECT
            retry_actions = [
                ("initial check", None),
                ("pressing SELECT", lambda: (self.device.select(), time.sleep(3))),
                ("re-clicking Edit button", lambda: (self.ui.click_by_id(editable_id, timeout=15), time.sleep(5))),
                ("pressing SELECT again", lambda: (self.device.select(), time.sleep(3))),
            ]

            for attempt_label, action in retry_actions:
                if transponder_el is not None:
                    break
                if action is not None:
                    log.info(f"[STEP 10] Transponder not found — {attempt_label}…")
                    try:
                        action()
                    except Exception as e:
                        log.warning(f"[STEP 10] Action '{attempt_label}' failed: {e}")
                try:
                    transponder_el = self.ui.find_by_uiautomator(transponder_selector, timeout=15)
                    log.info(f"[STEP 10] Transponder setup found after {attempt_label}")
                except Exception as e:
                    log.warning(f"[STEP 10] Transponder setup not found after {attempt_label}: {e}")

            ss10 = self._take_step_screenshot(10, "transponder_setup")

            if transponder_el is None:
                _record_step(10, "Verify Transponder Setup",
                             "Transponder setup text not found on screen after all retries",
                             "FAILED", ss10, "Transponder setup not found")
                raise AssertionError("Transponder setup text not found after all retries")
            log.info("[STEP 10] ✓ Transponder setup screen verified")
            _record_step(10, "Verify Transponder Setup",
                         "Verified Transponder setup screen after Edit",
                         "PASSED", ss10)

            select_btn = UI_IDS.get("select_button", "select_button")
            select_btn_id = f"{TATASKY_PACKAGE}:id/{select_btn}"

            # ─────────────────────────────────────────────────────────
            # STEP 11 — Enter Frequency digits via keypress
            # ─────────────────────────────────────────────────────────
            current_step = 11
            log.info(f"[STEP 11] Entering frequency: {FREQUENCY}…")
            freq_digits = _parse_digits(FREQUENCY)
            log.info(f"[STEP 11] Frequency digits: {freq_digits}")

            # Press UP to focus on the frequency row
            self.device.up()
            time.sleep(0.5)

            # Press digit keys one by one (KEYCODE_0=7 .. KEYCODE_9=16)
            for digit in freq_digits:
                keycode = 7 + int(digit)
                self.ui.press_keycode(keycode)
                log.info(f"[STEP 11] Pressed key for digit '{digit}' (keycode={keycode})")
                time.sleep(0.3)

            ss11 = self._take_step_screenshot(11, "frequency_entered")
            log.info(f"[STEP 11] ✓ Frequency {FREQUENCY} entered")
            _record_step(11, "Enter Frequency",
                         f"Entered frequency {FREQUENCY} via keypress",
                         "PASSED", ss11)

            # ─────────────────────────────────────────────────────────
            # STEP 12 — Set Polarization
            # ─────────────────────────────────────────────────────────
            current_step = 12
            log.info(f"[STEP 12] Setting polarization to '{POLARIZATION}'…")
            text_view_id = f"{TATASKY_PACKAGE}:id/{UI_IDS.get('text_view', 'textView')}"

            # Press DOWN to reach polarization row
            self.device.navigate_down(1)
            time.sleep(0.5)

            pol_matched = False
            for attempt in range(1, MAX_CLICK_ATTEMPTS + 1):
                current_pol = self.ui.get_text_by_id(text_view_id, timeout=12)
                log.info(f"[STEP 12] Attempt {attempt}: current polarization = '{current_pol}'")
                if current_pol.strip().upper() == POLARIZATION.upper():
                    pol_matched = True
                    break
                # Press RIGHT to cycle to next polarization option
                self.device.navigate_right(1)
                time.sleep(2)

            ss12 = self._take_step_screenshot(12, "polarization_set")
            if not pol_matched:
                _record_step(12, "Set Polarization",
                             f"Polarization '{POLARIZATION}' not matched after {MAX_CLICK_ATTEMPTS} attempts",
                             "FAILED", ss12,
                             f"Polarization '{POLARIZATION}' not matched")
                raise AssertionError(f"Polarization '{POLARIZATION}' not found after {MAX_CLICK_ATTEMPTS} attempts")
            log.info(f"[STEP 12] ✓ Polarization set to '{POLARIZATION}'")
            _record_step(12, "Set Polarization",
                         f"Cycled through options until polarization = '{POLARIZATION}'",
                         "PASSED", ss12)

            # ─────────────────────────────────────────────────────────
            # STEP 13 — Enter Symbol Rate digits via keypress
            # ─────────────────────────────────────────────────────────
            current_step = 13
            log.info(f"[STEP 13] Entering symbol rate: {SYMBOL_RATE}…")
            sr_digits = _parse_digits(SYMBOL_RATE)
            log.info(f"[STEP 13] Symbol rate digits: {sr_digits}")

            # Press DOWN to reach symbol rate row, then SELECT to focus
            self.device.navigate_down(1)
            time.sleep(0.5)
            self.device.select()
            time.sleep(0.5)

            # Press digit keys one by one
            for digit in sr_digits:
                keycode = 7 + int(digit)
                self.ui.press_keycode(keycode)
                log.info(f"[STEP 13] Pressed key for digit '{digit}' (keycode={keycode})")
                time.sleep(0.3)

            ss13 = self._take_step_screenshot(13, "symbol_rate_entered")
            log.info(f"[STEP 13] ✓ Symbol rate {SYMBOL_RATE} entered")
            _record_step(13, "Enter Symbol Rate",
                         f"Entered symbol rate {SYMBOL_RATE} via keypress",
                         "PASSED", ss13)

            # ─────────────────────────────────────────────────────────
            # STEP 14 — Click Select button to confirm transponder
            # ─────────────────────────────────────────────────────────
            current_step = 14
            log.info("[STEP 14] Clicking Select button to confirm…")
            self.ui.click_by_id(select_btn_id, timeout=15)
            time.sleep(5)
            ss14 = self._take_step_screenshot(14, "select_confirmed")
            log.info("[STEP 14] ✓ Select button clicked")
            _record_step(14, "Click Select to Confirm",
                         "Clicked Select button to confirm transponder setup",
                         "PASSED", ss14)

            # ─────────────────────────────────────────────────────────
            # STEP 15 — Click Next button
            # ─────────────────────────────────────────────────────────
            current_step = 15
            log.info("[STEP 15] Clicking Next button…")
            self.ui.click_by_id(next_btn_id, timeout=15)
            time.sleep(5)
            ss15 = self._take_step_screenshot(15, "next_after_select")
            log.info("[STEP 15] ✓ Next button clicked")
            _record_step(15, "Click Next Button",
                         "Clicked Next button after transponder confirm",
                         "PASSED", ss15)

            # ─────────────────────────────────────────────────────────
            # STEP 16 — Wait for Continue button and click it
            # ─────────────────────────────────────────────────────────
            current_step = 16
            log.info("[STEP 16] Waiting for Continue button to appear…")
            continue_btn = UI_IDS.get("continue_button", "continue_button")
            continue_btn_id = f"{TATASKY_PACKAGE}:id/{continue_btn}"
            continue_selector = f'new UiSelector().resourceId("{continue_btn_id}")'

            # This may take a while — wait up to 120 seconds for button visibility
            continue_el = self.ui.find_by_uiautomator(continue_selector, timeout=180)
            if continue_el is None:
                raise AssertionError("Continue button not detected within 120 seconds")

            # Use D-pad navigation instead of direct click: RIGHT then SELECT
            self.device.navigate_right(2)
            time.sleep(3)
            self.device.select()
            time.sleep(7)
            ss16 = self._take_step_screenshot(16, "continue_clicked")
            log.info("[STEP 16] ✓ Continue button detected and activated via RIGHT + SELECT")
            _record_step(16, "Click Continue Button",
                         "Waited for Continue button, then used RIGHT + SELECT",
                         "PASSED", ss16)

            # ─────────────────────────────────────────────────────────
            # STEP 17 — Press HOME and tune to channel
            # ─────────────────────────────────────────────────────────
            current_step = 17
            # Press channel number digits one by one
            for digit in SIGNAL_CHECK_CHANNEL:
                keycode = 7 + int(digit)
                self.ui.press_keycode(keycode)
                log.info(f"[STEP 17] Pressed key for digit '{digit}' (keycode={keycode})")
                time.sleep(0.3)
            time.sleep(7)

            ss17 = self._take_step_screenshot(17, "channel_tuned")
            log.info(f"[STEP 17] ✓ Tuned to channel {SIGNAL_CHECK_CHANNEL}")
            _record_step(17, "Tune to Channel",
                         f"Pressed HOME and tuned to channel {SIGNAL_CHECK_CHANNEL}",
                         "PASSED", ss17)

            # ─────────────────────────────────────────────────────────
            # STEP 18 — Press 04 + SELECT to open signal test
            # ─────────────────────────────────────────────────────────
            current_step = 18
            log.info("[STEP 18] Pressing 04 then SELECT…")
            self.ui.press_keycode(7)   # KEYCODE_0
            time.sleep(0.5)
            self.ui.press_keycode(11)  # KEYCODE_4
            time.sleep(0.5)
            self.device.select()
            time.sleep(7)
            ss18 = self._take_step_screenshot(18, "signal_test_opened")
            log.info("[STEP 18] ✓ Signal test opened")
            _record_step(18, "Open Signal Test",
                         "Pressed 04 + SELECT to open signal test screen",
                         "PASSED", ss18)

            # ─────────────────────────────────────────────────────────
            # STEP 19 — Verify signal strength > minimum %
            # ─────────────────────────────────────────────────────────
            current_step = 19
            log.info(f"[STEP 19] Checking signal strength (min {SIGNAL_STRENGTH_MIN}%)…")
            signal_id = f"{TATASKY_PACKAGE}:id/{UI_IDS.get('signal_strength', 'signal_test_signal_strength')}"
            signal_text = self.ui.get_text_by_id(signal_id, timeout=15)
            log.info(f"[STEP 19] Signal strength text: '{signal_text}'")

            # Extract numeric value from text like "45%" or "45"
            signal_value = int(''.join(ch for ch in signal_text if ch.isdigit()) or '0')
            log.info(f"[STEP 19] Signal strength value: {signal_value}%")

            ss19 = self._take_step_screenshot(19, "signal_strength")
            if signal_value > SIGNAL_STRENGTH_MIN:
                log.info(f"[STEP 19] ✓ Signal strength {signal_value}% > {SIGNAL_STRENGTH_MIN}% — PASSED")
                _record_step(19, "Verify Signal Strength",
                             f"Signal strength {signal_value}% is above minimum {SIGNAL_STRENGTH_MIN}%",
                             "PASSED", ss19)
            else:
                _record_step(19, "Verify Signal Strength",
                             f"Signal strength {signal_value}% is NOT above minimum {SIGNAL_STRENGTH_MIN}%",
                             "FAILED", ss19,
                             f"Signal strength {signal_value}% <= {SIGNAL_STRENGTH_MIN}%")
                raise AssertionError(
                    f"Signal strength {signal_value}% is not above {SIGNAL_STRENGTH_MIN}%"
                )

            log.info("=" * 60)
            log.info("TEST PASSED — LNB Settings setup complete")

        except Exception as e:
            status = "FAILED"
            error_message = str(e)
            log.error(f"TEST FAILED at step {current_step}: {e}", exc_info=True)

            # Mark remaining steps as SKIPPED
            recorded_nums = {s["step_number"] for s in step_results}
            all_step_names = {
                1: "Verify Home Screen",
                2: "Navigate to User Preferences",
                3: "Verify USER PREFERENCES Title",
                4: "Click System Settings",
                5: "Verify Satellite Settings",
                6: "Verify LNB Settings",
                7: "Select LNB Type",
                8: "Click Next Button",
                9: "Click Edit Button",
                10: "Verify Transponder Setup",
                11: "Enter Frequency",
                12: "Set Polarization",
                13: "Enter Symbol Rate",
                14: "Click Select to Confirm",
                15: "Click Next Button",
                16: "Click Continue Button",
                17: "Tune to Channel",
                18: "Open Signal Test",
                19: "Verify Signal Strength",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_lnb_settings_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:
            # ── Module-wise step-by-step Excel sheet ──────────────────
            self.report_gen.add_module_report(
                module_name="LNB Settings Setup",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
            )

            log.info(f"[RESULT] Status={status}")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)
