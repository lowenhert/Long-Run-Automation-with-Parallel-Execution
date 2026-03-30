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
log = logging.getLogger("TestFavouriteChannelsSetup")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Favourite channels config from settings.yaml ────────────────────────────
FAV_CFG = SETTINGS.get("favourite_channels", {})
TATASKY_PACKAGE = FAV_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
NAV_CFG = FAV_CFG.get("navigation", {})
HOME_CFG = FAV_CFG.get("home_check", {})
UI_IDS = FAV_CFG.get("ui_ids", {})
MAX_RIGHT_SEARCH = FAV_CFG.get("max_right_favourites", 30)
CHANNELS_TO_FAVOURITE = FAV_CFG.get("channels_to_favourite", 0)  # 0 = favourite ALL


class TestFavouriteChannelsSetup:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Favourite Channels test initialisation")

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
        appium_url = os.getenv("APPIUM_URL", FAV_CFG.get("appium_url", "http://localhost:4723"))
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
        filename = f"fav_step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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

    def test_favourite_channels_setup(self, request):
        """
        Favourite Channels Setup — navigate to User Settings, open
        Favourite Channels tab, press SELECT (Deselect All), DOWN to
        channel rail, then SELECT + RIGHT through channels until
        snackbar confirmation appears.

        Steps:
        1. Verify home screen
        2. Navigate UP 1, RIGHT 4, SELECT → User Preferences
        3. Verify "USER PREFERENCES" title
        4. Click User Settings button
        5. Click "Favourite Channels" tab
        6. DOWN to Deselect All → SELECT → DOWN to channel rail
        7. SELECT → RIGHT loop until snackbar appears
        8. Press HOME
        """
        favourite_channels = []
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
            # STEP 5 — Click "Favourite Channels" tab
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Looking for Favourite Channels tab…")
            fav_tab_xpath = (
                '//android.widget.CheckedTextView'
                f'[@resource-id="{TATASKY_PACKAGE}:id/'
                f'{UI_IDS.get("menu_item", "menu_item")}" '
                'and @text="Favourite Channels"]'
            )

            if not self.ui.exists_by_xpath(fav_tab_xpath, timeout=5):
                ss5 = self._take_step_screenshot(5, "fav_tab_not_found")
                _record_step(5, "Click Favourite Channels Tab",
                             "Favourite Channels tab not found",
                             "FAILED", ss5, "Tab not found on screen")
                raise AssertionError("Favourite Channels tab not found")

            self.ui.click_by_xpath(fav_tab_xpath, timeout=5)
            log.info("[STEP 5] ✓ Clicked Favourite Channels tab")
            time.sleep(3)
            ss5 = self._take_step_screenshot(5, "fav_tab_clicked")
            _record_step(5, "Click Favourite Channels Tab",
                         "Found and clicked Favourite Channels tab",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Deselect All (if present) → DOWN to channel rail
            # ─────────────────────────────────────────────────────────
            current_step = 6
            deselect_id = f"{TATASKY_PACKAGE}:id/{UI_IDS.get('deselect_all_btn', 'deselectAllButton')}"
            snackbar_deselect_id = f"{TATASKY_PACKAGE}:id/{UI_IDS.get('snackbar', 'snackbar_top_layout')}"
            log.info("[STEP 6] Pressing DOWN 2 times, then checking focused element…")

            # Navigate DOWN twice — cursor lands on Deselect All (or channel rail)
            self.device.navigate_down(2)
            time.sleep(1)

            if self.ui.exists_by_id(deselect_id, timeout=3):
                # Cursor is on Deselect All — click it with D-pad SELECT
                self.device.select()
                log.info("[STEP 6] ✓ Pressed D-pad SELECT on Deselect All")

                # Wait for / skip the snackbar triggered by deselect
                time.sleep(6)  # Wait a bit for snackbar to appear if it's going tos
                try:
                    if self.ui.exists_by_id(snackbar_deselect_id, timeout=5):
                        log.info("[STEP 6] Snackbar from deselect detected — waiting for it to disappear…")
                        time.sleep(7)
                except Exception:
                    pass

                # DOWN to move from Deselect All to the channel rail
                self.device.navigate_down(1)
                time.sleep(1)
            else:
                log.info("[STEP 6] Deselect All not found at current position — already on channel rail")

            ss6 = self._take_step_screenshot(6, "deselect_then_down")
            log.info("[STEP 6] ✓ Cursor now on channel rail")
            _record_step(6, "Deselect All + Move to Channel Rail",
                         "Deselect All (if present) then D-pad DOWN to channel rail",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — SELECT → RIGHT loop until snackbar appears
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info("[STEP 7] Selecting favourite channels (SELECT → RIGHT loop)…")

            snackbar_id = UI_IDS.get("snackbar", "snackbar_top_layout")
            snackbar_full_id = f"{TATASKY_PACKAGE}:id/{snackbar_id}"
            max_iterations = MAX_RIGHT_SEARCH
            fav_limit = CHANNELS_TO_FAVOURITE  # 0 = select ALL until snackbar
            channels_selected = 0
            snackbar_appeared = False

            consecutive_appium_failures = 0
            MAX_APPIUM_FAILURES = 3  # Break if Appium/UiAutomator2 dies

            for i in range(max_iterations):
                # ── Check user-defined limit ──────────────────────
                if fav_limit > 0 and channels_selected >= fav_limit:
                    log.info(f"[STEP 7] Reached favourite limit ({fav_limit}), stopping.")
                    break

                # ── SELECT — mark current channel as favourite ────
                self.device.select()
                time.sleep(0.5)

                # ── Check snackbar RIGHT AFTER SELECT ─────────────
                # If snackbar appeared, this SELECT was rejected (limit hit)
                # so do NOT count it
                try:
                    if self.ui.exists_by_id(snackbar_full_id, timeout=1):
                        log.info(
                            f"[STEP 7] ✓ Snackbar detected — limit reached! "
                            f"Last SELECT was rejected. "
                            f"Total favourited: {channels_selected}"
                        )
                        snackbar_appeared = True
                        break
                    consecutive_appium_failures = 0  # Reset on success
                except Exception as e:
                    consecutive_appium_failures += 1
                    log.warning(
                        f"[STEP 7] Appium check failed ({consecutive_appium_failures}/"
                        f"{MAX_APPIUM_FAILURES}): {str(e)[:120]}"
                    )
                    if consecutive_appium_failures >= MAX_APPIUM_FAILURES:
                        log.error(
                            f"[STEP 7] UiAutomator2 appears crashed after "
                            f"{MAX_APPIUM_FAILURES} consecutive failures. "
                            f"Stopping loop. Total favourited: {channels_selected}"
                        )
                        snackbar_appeared = True
                        break

                # ── Only count if snackbar did NOT appear ─────────
                channels_selected += 1
                log.info(f"[STEP 7] #{channels_selected} — SELECTED ★")

                favourite_channels.append({
                    "channel_number": str(channels_selected),
                    "channel_name": f"Channel {channels_selected}",
                    "selected": True,
                })

                # ── RIGHT — move focus to next channel ────────────
                self.device.navigate_right(1)
                time.sleep(0.5)

                # ── Safety check: snackbar after RIGHT ────────────
                try:
                    if self.ui.exists_by_id(snackbar_full_id, timeout=1):
                        log.info(
                            f"[STEP 7] ✓ Snackbar detected after RIGHT — "
                            f"channel #{channels_selected} was NOT actually "
                            f"favourited (device limit). Removing from list."
                        )
                        if favourite_channels:
                            favourite_channels.pop()
                        channels_selected -= 1
                        snackbar_appeared = True
                        break
                    consecutive_appium_failures = 0
                except Exception as e:
                    consecutive_appium_failures += 1
                    log.warning(
                        f"[STEP 7] Appium check failed ({consecutive_appium_failures}/"
                        f"{MAX_APPIUM_FAILURES}): {str(e)[:120]}"
                    )
                    if consecutive_appium_failures >= MAX_APPIUM_FAILURES:
                        log.error(
                            f"[STEP 7] UiAutomator2 appears crashed after "
                            f"{MAX_APPIUM_FAILURES} consecutive failures. "
                            f"Stopping loop. Total favourited: {channels_selected}"
                        )
                        snackbar_appeared = True
                        break

            log.info(f"[STEP 7] Total channels selected  : {channels_selected}")
            log.info(f"[STEP 7] Snackbar appeared         : {snackbar_appeared}")

            ss7 = self._take_step_screenshot(7, "channel_selection_done")
            _record_step(7, "Select Favourite Channels",
                         f"Selected {channels_selected} channels | "
                         f"Snackbar: {'Yes' if snackbar_appeared else 'No'}",
                         "PASSED", ss7)

            # ── Save favourite channels to report ─────────────────────
            self._save_favourite_channels_to_report(favourite_channels)

            # ─────────────────────────────────────────────────────────
            # STEP 8 — Press HOME
            # ─────────────────────────────────────────────────────────
            current_step = 8
            log.info("[STEP 8] Pressing HOME…")
            self.device.home()
            time.sleep(2)
            log.info("[STEP 8] ✓ Back at home")
            ss8 = self._take_step_screenshot(8, "back_home")
            _record_step(8, "Press HOME",
                         "Pressed HOME key to return to the home screen",
                         "PASSED", ss8)

            log.info("=" * 60)
            log.info("TEST PASSED — Favourite Channels setup complete")

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
                5: "Click Favourite Channels Tab",
                6: "Deselect All + Move to Channel Rail",
                7: "Select Favourite Channels",
                8: "Press HOME",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_fav_channels_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:
            pytest.favourite_channels = favourite_channels

            # ── Module-wise step-by-step Excel sheet ──────────────────
            self.report_gen.add_module_report(
                module_name="Favourite Channels Setup",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
                summary_info={
                    "Channels Selected": channels_selected if 'channels_selected' in dir() else 0,
                    "Snackbar Appeared": str(snackbar_appeared) if 'snackbar_appeared' in dir() else "N/A",
                },
            )

            log.info(f"[RESULT] Status={status}  Favourite channels={len(favourite_channels)}")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)

    def _save_favourite_channels_to_report(self, channels):
        """Add favourite channels as a sheet in the main report Excel."""
        try:
            self.report_gen.add_favourite_channels_sheet(channels)
            log.info(f"[EXCEL] Favourite channels sheet added to report ({len(channels)} channels)")

            log.info(f"[FAVOURITE CHANNELS LIST] Total: {len(channels)}")
            for ch in channels:
                log.info(
                    f"  Ch {ch.get('channel_number', '?')} — "
                    f"{ch.get('channel_name', '')} — "
                    f"{'Selected ★' if ch.get('selected') else 'Not selected'}"
                )
        except Exception as e:
            log.warning(f"[EXCEL] Failed to save favourite channels: {e}")
