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
log = logging.getLogger("TestSoundConfiguration")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Sound Configuration from settings.yaml ────────────────────────────
Audio_CFG = SETTINGS.get("Audio", {})
TATASKY_PACKAGE = Audio_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
NAV_CFG = Audio_CFG.get("navigation", {})
Audio_Nav=Audio_CFG.get("navigation_audio",{})
HOME_CFG = Audio_CFG.get("home_check", {})
UI_IDS = Audio_CFG.get("ui_ids", {})


class TestSoundConfigurationSetup:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Sound Configuration test initialisation")

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
        appium_url = os.getenv("APPIUM_URL", Audio_CFG.get("appium_url", "http://localhost:4723"))
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
        log.info("CLEANUP — navigating back/home")
        try:
            home_logo_path = LOGO_DIR / HOME_CFG.get("logo_file", "Home.png")
            navigate_back_until_home(
                device=self.device,
                logo_compare=self.logo_compare,
                home_logo_path=home_logo_path,
                home_region=HOME_CFG.get("region", [90, 120, 260, 180]),
                home_threshold=HOME_CFG.get("threshold", 0.60),
                max_back_presses=HOME_CFG.get("max_back_presses", 10),
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
        filename = f"audio_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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

    def test_sound_configuration(self, request):
        step_results = []

        status = "PASSED"
        error_message = ""
        current_step = 0

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
            # STEP 2 — Navigate to Android Settings (UP 1, RIGHT 3, SELECT)
            # ─────────────────────────────────────────────────────────
            current_step = 2
            log.info("[STEP 2] Navigating UP , RIGHT, SELECT → Android Settings")
            for _ in range(1):
                self.device.up()
                time.sleep(0.3)
            self.device.navigate_right(3)
            time.sleep(0.5)
            self.device.select()
            time.sleep(5)
            ss2 = self._take_step_screenshot(2, "Android_Settings")
            _record_step(2, "Navigate to Android Settings",
                         "Pressed UP , RIGHT, SELECT to open Android Settings",
                         "PASSED", ss2)

            # ─────────────────────────────────────────────────────────
            # STEP 3 — Navigate to Device Preference (DPAD BACK + re-check up to 5 times)
            # ─────────────────────────────────────────────────────────
            current_step = 3
            dev_pref_id = ('//android.widget.TextView[@resource-id="android:id/title" and @text="Device Preferences"]')
            dev_pref_found = False
            for _retry in range(5):
                log.info(f"[STEP 3] Checking for Device Preferences… (attempt {_retry + 1}/5)")
                if self.ui.exists_by_xpath(dev_pref_id, timeout=5):
                    log.info("[STEP 3] ✓ Device Preference detected")
                    dev_pref_found = True
                    break
                log.warning(f"[STEP 3] Device Preference not found (attempt {_retry + 1}/5), pressing DPAD BACK…")
                self.device.back()
                time.sleep(3)
            ss3 = self._take_step_screenshot(3, "Device_Preferences")
            if dev_pref_found:
                _record_step(3, "Verify Device Preference screen",
                             "Device Preference screen confirmed",
                             "PASSED", ss3)
                self.ui.click_by_xpath(dev_pref_id, timeout=12)
            else:
                log.info("[STEP 3] Device Preference not detected after 5 attempts")
                _record_step(3, "Verify Device Preference screen",
                             "Device Preference screen not confirmed after 5 attempts",
                             "FAILED", ss3)
                raise AssertionError("Device Preference not detected after 5 attempts")

            # ─────────────────────────────────────────────────────────
            # STEP 4 — Navigate and Launch Sound Settings
            # ─────────────────────────────────────────────────────────
            current_step = 4
            sound_settings_btn = ('//android.widget.TextView[@resource-id="android:id/title" and @text="Sound"]')

            log.info(f"[STEP 4] Looking for sound settings ")
            count=0
            ss4 = self._take_step_screenshot(4, "Sound_Settings")

            if self.ui.exists_by_xpath(sound_settings_btn,timeout=5):
                self.ui.click_by_xpath(sound_settings_btn, timeout=12)
                count=1
                log.info("[STEP 4] ✓ Sound Settings launched")
                _record_step(4, "Sound Settings",
                             "Found and clicked Sound Settings",
                             "PASSED", ss4)
                time.sleep(5)
            else:
                log.warning("[STEP 4] Sound Settings not found")
                _record_step(4, "Sound Settings",
                             "Sound Settings not found",
                             "FAILED", ss4)
                raise AssertionError("[STEP 4] Sound Settings button not found")


            # ─────────────────────────────────────────────────────────
            # STEP 5 — Click Advance sound settings and Launch
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Looking for Advance Sound Settings")
            Adv_tab_xpath = (
                '//android.widget.TextView[@resource-id="android:id/title" and @text="Advanced sound settings"]'
            )

            if not self.ui.exists_by_xpath(Adv_tab_xpath, timeout=12):
                ss5 = self._take_step_screenshot(5, "Advance_sound_settings")
                _record_step(5, "Launch Advance Sound Settings",
                             "Advance Sound Settings not found",
                             "FAILED", ss5, "Advance Sound Settings not found on screen")
                raise AssertionError("Advance Sound Settings not found")

            self.ui.click_by_xpath(Adv_tab_xpath, timeout=12)
            log.info("[STEP 5] ✓ Clicked Advance Sound Settings tab")
            time.sleep(5)
            ss5 = self._take_step_screenshot(5, "Advance_Sound_Settings_clicked")
            _record_step(5, "Launch Advance Sound Settings Tab",
                         "Found and launched Advance Sound Settings tab",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Launch Select Formats
            # ─────────────────────────────────────────────────────────
            Format_xpath = '//android.widget.TextView[@resource-id="android:id/title" and @text="Select formats"]'
            current_step = 6
            if not self.ui.exists_by_xpath(Format_xpath, timeout=12):
                ss6 = self._take_step_screenshot(6, "Select_Format_settings")
                _record_step(6, "Select Format Settings",
                             "Select Format not found",
                             "FAILED", ss6, "Select Format not found on screen")
                raise AssertionError("Select Format not found")

            self.ui.click_by_xpath(Format_xpath, timeout=12)
            log.info("[STEP 6] ✓ Clicked Format Settings tab")
            time.sleep(5)
            ss6 = self._take_step_screenshot(5, "Select_Format_clicked")
            _record_step(6, "Launch Select Format Tab",
                         "Found and launched Select Format tab",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Verify Sound Format as Always
            # ─────────────────────────────────────────────────────────
            Always_icon_xpath = ('//android.widget.TextView[@resource-id="android:id/title" and @text="Always: always use Dolby"]')
            current_step = 7
            log.info("[Step 7]Checking resolution as Always exists")
            ss7 = self._take_step_screenshot(7, "Select_Format_Menu_Launched")

            if not self.ui.exists_by_xpath(Always_icon_xpath, timeout=12):
                ss7 = self._take_step_screenshot(7, "Always_icon_settings")
                _record_step(7, "Sound Format - Always",
                             "Selected Format not found",
                             "FAILED", ss7, "Always Format not found on screen")
                raise AssertionError("Always Format not found")

            else:
                log.info("[STEP 7] ✓ Format:Always Detected")
                _record_step(7, "Sound Format - Always",
                             "Sound Format - Always exists",
                             "PASSED", ss7)

            # ─────────────────────────────────────────────────────────
            # STEP 8 — Select Sound Format as Always
            # ─────────────────────────────────────────────────────────
            current_step = 8
            log.info("[Step 8]Selecting Always as Format")
            self.ui.click_by_xpath(Always_icon_xpath,timeout=12)
            time.sleep(3)
            ss8 = self._take_step_screenshot(8, "Always_Format_clicked")

            Format_text_summary_id="android:id/summary"
            Format_text_summary=self.ui.get_text_by_id(Format_text_summary_id)

            log.info("[Step 8]Verifying Always selected as Format")
            if not Format_text_summary=="Always: always use Dolby":
                ss8 = self._take_step_screenshot(8, "Final_Format_Selected")
                _record_step(8, "Final Format - Always",
                             "Final Format as Always not found",
                             "FAILED", ss8, "Always as Final Format not found on screen")
                raise AssertionError("Always Format as final not found")

            else:
                log.info("[STEP 8] ✓ Format verified as Always")
                _record_step(8, "Sound Format - Always as Final",
                             "Sound Format - Always selected",
                             "PASSED", ss8)

            # ─────────────────────────────────────────────────────────
            # STEP 9 — Press HOME
            # ─────────────────────────────────────────────────────────
            current_step = 9
            log.info("[STEP 9] Pressing Back 5 times…")
            self.device.back()
            time.sleep(2)
            log.info("Pressing back")
            self.device.back()
            time.sleep(2)
            log.info("Pressing back")
            self.device.back()
            time.sleep(2)
            log.info("Pressing back")
            self.device.back()
            log.info("[STEP 9] Pressing Home…")
            self.device.home()
            time.sleep(3)
            log.info("[STEP 9] ✓ Back at home")
            ss9 = self._take_step_screenshot(9, "back_home")
            _record_step(9, "Press HOME",
                         "Pressed HOME key to return to the home screen",
                         "PASSED", ss9)

            log.info("=" * 60)
            log.info("TEST PASSED — Audio change setup complete")

        except Exception as e:
            status = "FAILED"
            error_message = str(e)
            log.error(f"TEST FAILED at step {current_step}: {e}", exc_info=True)

            # Mark remaining steps as SKIPPED
            recorded_nums = {s["step_number"] for s in step_results}
            all_step_names = {
                1: "Verify Home Screen",
                2: "Navigate to Android Settings",
                3: "Launch Device Preferences",
                4: "Launch Sound Settings",
                5: "Launch Advance Sound Settings UI",
                6: "Launch Select Format UI",
                7: "Always option detected",
                8: "Crosscheck Format selected as Always",
                9: "Press HOME",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_sound_configuration_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:

            # ── Module-wise step-by-step Excel sheet ──────────────────
            self.report_gen.add_module_report(
                module_name="Sound Configuration Setup",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
            )

            log.info(f"[RESULT] Status={status} ")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)

