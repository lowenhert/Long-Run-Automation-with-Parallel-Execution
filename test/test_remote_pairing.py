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
log = logging.getLogger("TestRemotePairing")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Remote pairing config from settings.yaml ───────────────────────────────
RP_CFG = SETTINGS.get("remote_pairing", {})
NAV_CFG = RP_CFG.get("navigation", {})
HOME_CFG = RP_CFG.get("home_check", {})
UI_IDS = RP_CFG.get("ui_ids", {})
EXPECTED = RP_CFG.get("expected_texts", {})


class TestRemotePairing:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Remote Pairing check initialisation")

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

        # ── Appium session (no specific appPackage — we navigate to
        #    Android TV Settings via D-pad after the home check) ──────
        appium_url = os.getenv("APPIUM_URL", RP_CFG.get("appium_url", "http://localhost:4723"))
        self.driver = AppiumDriver.create(
            device_id=self.device_id,
            app_package="",
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
        filename = f"remote_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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

    def test_remote_pairing_check(self, request):
        """
        Remote Pairing Check — navigate to Android TV Settings →
        Remotes and accessories, then verify whether a remote is
        connected.

        Steps:
        1. Verify home screen
        2. Navigate UP 1, RIGHT 3, SELECT → Android TV Settings
        3. Verify "Settings" title on the Settings screen
        4. Click "Remotes and accessories"
        5. Verify "Remotes and accessories" title
        6. Check list for connected remote
        7. Press HOME
        """
        step_results = []

        status = "PASSED"
        error_message = ""
        current_step = 0
        remote_connected = False

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
            time.sleep(5)
            ss2 = self._take_step_screenshot(2, "android_settings_nav")
            _record_step(2, "Navigate to Android TV Settings",
                         f"Pressed UP {up_count}, RIGHT {right_count}, SELECT to open Settings",
                         "PASSED", ss2)

            # ─────────────────────────────────────────────────────────
            # STEP 3 — Verify "Settings" title (DPAD BACK + re-check up to 5 times)
            # ─────────────────────────────────────────────────────────
            current_step = 3
            settings_title_id = UI_IDS.get("settings_title", "com.android.tv.settings:id/decor_title")
            expected_settings_text = EXPECTED.get("settings", "Settings")
            title_verified = False
            title_text = ""
            for _retry in range(5):
                log.info(f"[STEP 3] Verifying Settings title… (attempt {_retry + 1}/5)")
                try:
                    title_text = self.ui.get_text_by_id(settings_title_id, timeout=10)
                except Exception:
                    title_text = ""
                log.info(f"[STEP 3] Title text: '{title_text}'")
                if expected_settings_text.upper() in title_text.upper():
                    title_verified = True
                    break
                log.warning(f"[STEP 3] Title not found (attempt {_retry + 1}/5), pressing DPAD BACK…")
                self.device.back()
                time.sleep(3)
            ss3 = self._take_step_screenshot(3, "settings_title")
            if not title_verified:
                _record_step(3, "Verify Settings Title",
                             f"Expected '{expected_settings_text}' but got '{title_text}' after 5 attempts",
                             "FAILED", ss3, f"Got '{title_text}' after 5 retries")
                raise AssertionError(
                    f"Expected '{expected_settings_text}' but got '{title_text}' after 5 retries"
                )
            log.info("[STEP 3] ✓ Settings screen confirmed")
            _record_step(3, "Verify Settings Title",
                         f"Title shows '{title_text}' — Settings screen confirmed",
                         "PASSED", ss3)

            # ─────────────────────────────────────────────────────────
            # STEP 4 — Click "Remotes and accessories"
            # ─────────────────────────────────────────────────────────
            current_step = 4
            log.info("[STEP 4] Clicking 'Remotes and accessories'…")
            remotes_text = EXPECTED.get("remotes_accessories", "Remotes & accessories")
            remotes_uia = f'new UiSelector().text("{remotes_text}")'

            remotes_clicked = False
            max_retries = 3
            for _attempt in range(1, max_retries + 1):
                log.info(f"[STEP 4] Attempt {_attempt}/{max_retries} — finding element…")
                try:
                    remotes_el = self.ui.find_by_uiautomator(remotes_uia, timeout=12)
                    remotes_el.click()
                    remotes_clicked = True
                    break
                except Exception as e:
                    log.warning(f"[STEP 4] UiAutomator attempt {_attempt} failed: {e}")
                    if _attempt < max_retries:
                        time.sleep(3)
                        # Fallback: try click_by_text (XPath-based)
                        try:
                            log.info(f"[STEP 4] Trying click_by_text fallback…")
                            self.ui.click_by_text(remotes_text, timeout=12)
                            remotes_clicked = True
                            break
                        except Exception as e2:
                            log.warning(f"[STEP 4] click_by_text fallback also failed: {e2}")
                            time.sleep(3)

            if not remotes_clicked:
                ss4 = self._take_step_screenshot(4, "remotes_not_found")
                _record_step(4, "Click Remotes and Accessories",
                             f"'{remotes_text}' not found on Settings screen after {max_retries} attempts",
                             "FAILED", ss4,
                             f"'{remotes_text}' menu item not found")
                raise AssertionError(f"'{remotes_text}' menu item not found")
            log.info("[STEP 4] ✓ Clicked 'Remotes and accessories'")
            time.sleep(5)
            ss4 = self._take_step_screenshot(4, "remotes_clicked")
            _record_step(4, "Click Remotes and Accessories",
                         f"Found and clicked '{remotes_text}'",
                         "PASSED", ss4)

            # ─────────────────────────────────────────────────────────
            # STEP 5 — Verify "Remotes and accessories" title
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Verifying 'Remotes and accessories' title…")
            decor_title_id = UI_IDS.get("settings_title", "com.android.tv.settings:id/decor_title")
            decor_text = self.ui.get_text_by_id(decor_title_id, timeout=15)
            log.info(f"[STEP 5] Decor title text: '{decor_text}'")
            ss5 = self._take_step_screenshot(5, "remotes_title")
            if remotes_text.upper() not in decor_text.upper():
                _record_step(5, "Verify Remotes and Accessories Title",
                             f"Expected '{remotes_text}' but got '{decor_text}'",
                             "FAILED", ss5, f"Got '{decor_text}'")
                raise AssertionError(
                    f"Expected '{remotes_text}' but got '{decor_text}'"
                )
            log.info("[STEP 5] ✓ 'Remotes and accessories' screen confirmed")
            _record_step(5, "Verify Remotes and Accessories Title",
                         f"Title shows '{decor_text}' — screen confirmed",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Check list for connected remote
            # ─────────────────────────────────────────────────────────
            current_step = 6
            log.info("[STEP 6] Checking for connected remote…")
            menu_title_id = UI_IDS.get("menu_item_title", "android:id/title")
            list_id = UI_IDS.get("list_id", "com.android.tv.settings:id/list")
            summary_id = UI_IDS.get("summary", "android:id/summary")
            connected_text = EXPECTED.get("connected", "Connected")
            searching_text = EXPECTED.get("searching", "Searching for accessories")

            # First check: if "Searching for accessories…" is visible,
            # remote is definitely NOT paired
            searching_xpath = (
                f'//android.widget.TextView'
                f'[@resource-id="{menu_title_id}" '
                f'and contains(@text, "{searching_text}")]'
            )
            is_searching = self.ui.exists_by_xpath(searching_xpath, timeout=5)

            if is_searching:
                remote_connected = False
                log.warning("[STEP 6] ✗ 'Searching for accessories…' found — remote is NOT paired")
                ss6 = self._take_step_screenshot(6, "remote_searching")
                _record_step(6, "Check Remote Connection",
                             f"Remote is NOT CONNECTED — '{searching_text}' text found, "
                             "device is searching for accessories (no remote paired)",
                             "FAILED", ss6,
                             f"Remote not paired: '{searching_text}' is displayed")
                status = "FAILED"
                error_message = f"Remote not paired: '{searching_text}' is displayed"
            else:
                # Check if the list has children (more than one item)
                list_items = self.ui.find_all_by_xpath(
                    f'//*[@resource-id="{list_id}"]//*[@resource-id="{menu_title_id}"]',
                    timeout=12,
                )
                list_count = len(list_items) if list_items else 0
                log.info(f"[STEP 6] List items found: {list_count}")

                # Check for "Connected" summary text using UiAutomator
                connected_uia = f'new UiSelector().resourceId("{summary_id}").text("{connected_text}")'
                has_connected = False
                try:
                    connected_el = self.ui.find_by_uiautomator(connected_uia, timeout=8)
                    if connected_el:
                        log.info(f"[STEP 6] Found summary element with text '{connected_text}' via UiAutomator")
                        has_connected = True
                except Exception:
                    log.info(f"[STEP 6] '{connected_text}' summary not found via UiAutomator")

                ss6 = self._take_step_screenshot(6, "remote_check")

                if list_count > 1 and has_connected:
                    remote_connected = True
                    log.info("[STEP 6] ✓ Remote IS connected (list has >1 item and 'Connected' found)")
                    _record_step(6, "Check Remote Connection",
                                 f"Remote is CONNECTED — {list_count} items in list, "
                                 f"'{connected_text}' summary found",
                                 "PASSED", ss6)
                else:
                    remote_connected = False
                    reason = []
                    if list_count <= 1:
                        reason.append(f"list has {list_count} item(s) (need >1)")
                    if not has_connected:
                        reason.append(f"'{connected_text}' summary not found")
                    reason_str = "; ".join(reason)
                    log.warning(f"[STEP 6] ✗ Remote is NOT connected — {reason_str}")
                    _record_step(6, "Check Remote Connection",
                                 f"Remote is NOT CONNECTED — {reason_str}",
                                 "FAILED", ss6,
                                 f"Remote not connected: {reason_str}")
                    status = "FAILED"
                    error_message = f"Remote not connected: {reason_str}"

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Press BACK until home screen is detected
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info("[STEP 7] Pressing BACK until home screen is detected…")
            max_back_presses = RP_CFG.get("max_back_presses", 10)
            back_home_detected = False
            for back_attempt in range(1, max_back_presses + 1):
                self.device.back()
                time.sleep(1.5)
                try:
                    screenshot_bytes = self.device.take_screenshot_bytes()
                    self.logo_compare.fail_if_logo_not_present_bytes(
                        screenshot_bytes, str(home_logo_path),
                        x=hc_region[0], y=hc_region[1],
                        width=hc_region[2], height=hc_region[3],
                        threshold=hc_threshold,
                    )
                    log.info(f"[STEP 7] Home screen detected after {back_attempt} BACK press(es)")
                    back_home_detected = True
                    break
                except AssertionError:
                    log.info(f"[STEP 7] BACK press {back_attempt}/{max_back_presses} — not at home yet")

            ss7 = self._take_step_screenshot(7, "back_home")
            if not back_home_detected:
                log.warning(f"[STEP 7] Home not detected after {max_back_presses} BACK presses, pressing HOME as fallback")
                self.device.home()
                time.sleep(3)
                ss7 = self._take_step_screenshot(7, "back_home_fallback")

            _record_step(7, "Navigate Back to Home",
                         f"Pressed BACK {back_attempt} time(s) to return to home screen"
                         + (" (HOME fallback used)" if not back_home_detected else ""),
                         "PASSED", ss7)

            if remote_connected:
                log.info("=" * 60)
                log.info("TEST PASSED — Remote is connected")
            else:
                log.info("=" * 60)
                log.info("TEST FAILED — Remote is NOT connected")

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
                4: "Click Remotes and Accessories",
                5: "Verify Remotes and Accessories Title",
                6: "Check Remote Connection",
                7: "Navigate Back to Home",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_remote_pairing_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:
            # ── Module-wise step-by-step Excel sheet ──────────────────
            self.report_gen.add_module_report(
                module_name="Remote Pairing Check",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
                summary_info={
                    "Remote Connected": str(remote_connected),
                },
            )

            log.info(f"[RESULT] Status={status}  Remote Connected={remote_connected}")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)
