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
log = logging.getLogger("TestSoundConfiguration")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Sound config from settings.yaml ────────────────────────────
Audio_CFG = SETTINGS.get("Audio", {})
TATASKY_PACKAGE = Audio_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
NAV_CFG = Audio_CFG.get("navigation", {})
Audio_Nav=Audio_CFG.get("navigation_audio",{})
HOME_CFG = Audio_CFG.get("home_check", {})
UI_IDS = Audio_CFG.get("ui_ids", {})
#MAX_RIGHT_SEARCH = FAV_CFG.get("max_right_favourites", 30)
#CHANNELS_TO_FAVOURITE = FAV_CFG.get("channels_to_favourite", 0)  # 0 = favourite ALL


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
        filename = f"sound_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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
                    time.sleep(2)

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
            ss2 = self._take_step_screenshot(2, "user_preferences_nav")
            _record_step(2, "Navigate to User Preferences",
                         f"Pressed UP {up_count}, RIGHT {right_count}, SELECT to open User Preferences",
                         "PASSED", ss2)

            # ─────────────────────────────────────────────────────────
            # STEP 3 — Verify "USER PREFERENCES" title
            # ─────────────────────────────────────────────────────────
            current_step = 3
            log.info("[STEP 3] Verifying USER PREFERENCES title…")
            title_id = UI_IDS.get("title", "textViewTitle")
            title_text = self.ui.get_text_by_id(
                f"{TATASKY_PACKAGE}:id/{title_id}", timeout=10
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
            # STEP 4 — Click User Settings button
            # ─────────────────────────────────────────────────────────
            current_step = 4
            user_settings_btn = UI_IDS.get("user_settings_btn", "buttonUserSettings")
            user_settings_id = f"{TATASKY_PACKAGE}:id/{user_settings_btn}"
            log.info(f"[STEP 4] Looking for User Settings button ({user_settings_id})…")

            if not self.ui.exists_by_id(user_settings_id, timeout=5):
                ss4 = self._take_step_screenshot(4, "user_settings_not_found")
                _record_step(4, "Click User Settings",
                             "User Settings button not found",
                             "FAILED", ss4, "Button not found on screen")
                raise AssertionError(f"User Settings button ({user_settings_id}) not found")

            self.ui.click_by_id(user_settings_id, timeout=5)
            log.info("[STEP 4] ✓ Clicked User Settings button")
            time.sleep(3)
            ss4 = self._take_step_screenshot(4, "user_settings_clicked")
            _record_step(4, "Click User Settings",
                         "Found and clicked User Settings button",
                         "PASSED", ss4)

            # ─────────────────────────────────────────────────────────
            # STEP 5 — Click "Video" tab
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Looking for Video tab…")
            Video_tab_xpath = (
                '// android.widget.CheckedTextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/menu_item" and @text="Video"]'
            )

            if not self.ui.exists_by_xpath(Video_tab_xpath, timeout=5):
                ss5 = self._take_step_screenshot(5, "Video_tab_not_found")
                _record_step(5, "Click Video Tab",
                             "Video tab not found",
                             "FAILED", ss5, "Tab not found on screen")
                raise AssertionError("Video tab not found")

            self.ui.click_by_xpath(Video_tab_xpath, timeout=5)
            log.info("[STEP 5] ✓ Clicked Video Channels tab")
            time.sleep(3)
            ss5 = self._take_step_screenshot(5, "Video_tab_clicked")
            _record_step(5, "Click Video Channels Tab",
                         "Found and clicked Video Channels tab",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Navigate to audio → Change malayalam audio
            # ─────────────────────────────────────────────────────────
            tick_icon_xpath= ( '//android.widget.ImageView[@resource-id="tv.accedo.studio.paytv.tatasky:id/icon"]' )
            mal_xpath = '//android.widget.TextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/textView" and @text="Malayalam"]'
            current_step = 6
            down_count = Audio_Nav.get("navigate_down", 1)
            right_count = Audio_Nav.get("navigate_malayalam", 2)

            for i in range(down_count):
                self.device.navigate_down()

            for j in range(right_count):
                self.device.navigate_right()

            log.info("[STEP 6] ✓ Audio language change step")

            ss6 = self._take_step_screenshot(5, "Audio change")

            if self.ui.exists_by_xpath(mal_xpath, timeout=3):
                try:
                    if self.ui.exists_by_xpath(mal_xpath, timeout=5):
                        log.info("[STEP 6] Malayalam Language detected")
                        time.sleep(1)
                except AssertionError:
                    log.warning(f"[STEP 6] Malayalam Langauge not detected")
                    _record_step(6, "Audio change",
                                 "Audio not changed to Malayalam ",
                                 "FAILED", ss6)
            else:
                log.info("[STEP 6] Audio not changed")


           #checking Apply button
            self.device.navigate_down()
            self.device.navigate_down()
            Apply=UI_IDS.get("Apply_btn")

            if self.ui.exists_by_id(Apply, timeout=3):
                # Cursor is on Apply — click it with D-pad SELECT
                self.device.select()
                log.info("[STEP 6] ✓ Audio language changed , Apply button selected")

                # Wait for / skip the snackbar triggered by Apply
                time.sleep(1)  # Wait a bit for snackbar to appear
                ss6 = self._take_step_screenshot(6, "Audio change")
                try:
                    if self.ui.exists_by_xpath(tick_icon_xpath, timeout=5):
                        log.info("[STEP 6] Tick icon detected — waiting for it to disappear…")
                        time.sleep(7)
                except AssertionError:
                    log.warning(f"[STEP 6] Apply tick not detected")
                    _record_step(6, "Audio change",
                                 "Audio not changed to Malayalam ",
                                 "FAILED", ss6)
            else:
                log.info("[STEP 6] Audio not changed")
                _record_step(6, "Audio change",
                             "Audio not changed to Malayalam ",
                             "FAILED", ss6)

            log.info("[STEP 6] ✓ Audio changed")
            _record_step(6, "Audio change",
                         "Audio changed to Malayalam ",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Press HOME
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info("[STEP 7] Pressing HOME…")
            self.device.home()
            time.sleep(2)
            log.info("[STEP 7] ✓ Back at home")
            ss8 = self._take_step_screenshot(8, "back_home")
            _record_step(7, "Press HOME",
                         "Pressed HOME key to return to the home screen",
                         "PASSED", ss8)

            log.info("=" * 60)
            log.info("TEST PASSED — Sound Configuration setup complete")

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
                4: "Click User Settings",
                5: "Click Video Tab",
                6: "Change Audio to Malayalam",
                7: "Press HOME",
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

