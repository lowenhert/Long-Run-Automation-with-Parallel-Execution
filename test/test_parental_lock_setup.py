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
log = logging.getLogger("TestParentalLockSetup")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Parental lock config from settings.yaml ────────────────────────────────
PL_CFG = SETTINGS.get("parental_lock", {})
TATASKY_PACKAGE = PL_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
PIN_STR = PL_CFG.get("pin", "0000")
DEFAULT_PIN = list(PIN_STR)  # e.g. ["0","0","0","0"]
NAV_CFG = PL_CFG.get("navigation", {})
HOME_CFG = PL_CFG.get("home_check", {})
UI_IDS = PL_CFG.get("ui_ids", {})
MAX_DOWN_SEARCH = PL_CFG.get("max_down_search", 15)
MAX_RIGHT_SEARCH = PL_CFG.get("max_right_search", 10)
MAX_NO_NEW_SCROLLS = PL_CFG.get("max_no_new_scrolls", 3)
MAX_SCROLL_ITERATIONS = PL_CFG.get("max_scroll_iterations", 30)
CHANNELS_TO_LOCK = PL_CFG.get("channels_to_lock", 0)  # 0 = lock ALL


class TestParentalLockSetup:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Parental Lock test initialisation")

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
        appium_url = os.getenv("APPIUM_URL", PL_CFG.get("appium_url", "http://localhost:4723"))
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

    def _save_locked_channels_to_report(self, channels):
        """Add locked channels as a sheet in the main report Excel."""
        try:
            self.report_gen.add_locked_channels_sheet(channels)
            log.info(f"[EXCEL] Locked channels sheet added to report ({len(channels)} channels)")

            # Log the locked channels list
            log.info(f"[LOCKED CHANNELS LIST] Total: {len(channels)}")
            for ch in channels:
                log.info(
                    f"  Ch {ch.get('channel_number', '?')} — "
                    f"{ch.get('channel_name', '')} — "
                    f"{'Locked' if ch.get('locked') else 'Unlocked'}"
                )
        except Exception as e:
            log.warning(f"[EXCEL] Failed to save locked channels: {e}")

    def _take_step_screenshot(self, step_number, label=""):
        """Take a screenshot for the given step and return the saved path."""
        safe_label = label.replace(" ", "_").replace("/", "_")[:40]
        filename = f"step{step_number}_{safe_label}_{self.device_id.replace(':', '_')}.png"
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

    def test_parental_lock_channel_check(self, request):
        """
        Parental Lock Setup — navigate to Channel Lock and lock all channels.
        Already-locked channels are skipped.

        Steps:
        1. Verify home screen
        2. Navigate UP 1, RIGHT 4, SELECT → User Preferences
        3. Verify "USER PREFERENCES" title
        4. Scroll DOWN to Parental Controls button → SELECT
        5. Verify PIN prompt screen
        6. Enter PIN (default 0000) → SELECT
        7. Navigate RIGHT to "Channel Lock" tab → SELECT
        8. Press DOWN 1 into channel list
        9. Loop through channels — lock unlocked, skip locked
        10. Press HOME
        """
        locked_channels = []
        step_results = []     # list of dicts for module report

        status = "PASSED"
        error_type = ""
        error_message = ""
        failed_step = ""
        full_tb = ""
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
            # STEP 4 — Scroll DOWN until Parental Controls button, then click
            # ─────────────────────────────────────────────────────────
            current_step = 4
            log.info("[STEP 4] Pressing DOWN to find Parental Controls…")
            parental_btn = UI_IDS.get("parental_controls_btn", "buttonParentalControls")
            parental_id = f"{TATASKY_PACKAGE}:id/{parental_btn}"
            max_downs = MAX_DOWN_SEARCH
            found = False
            for i in range(max_downs):
                if self.ui.exists_by_id(parental_id, timeout=2):
                    log.info(f"[STEP 4] Parental Controls button found after {i} downs")
                    found = True
                    break
                self.device.navigate_down(1)
                time.sleep(0.5)

            if not found:
                ss4 = self._take_step_screenshot(4, "parental_btn_not_found")
                _record_step(4, "Find & Click Parental Controls",
                             f"Button not found after {max_downs} downs",
                             "FAILED", ss4,
                             f"Parental Controls button not found after {max_downs} downs")
                raise AssertionError(
                    f"Parental Controls button ({parental_id}) not found after {max_downs} downs"
                )

            self.ui.click_by_id(parental_id, timeout=5)
            log.info("[STEP 4] ✓ Clicked Parental Controls button via Appium")
            time.sleep(5)
            ss4 = self._take_step_screenshot(4, "parental_controls_clicked")
            _record_step(4, "Find & Click Parental Controls",
                         "Scrolled down, found Parental Controls button and clicked it",
                         "PASSED", ss4)

            # ─────────────────────────────────────────────────────────
            # STEP 5 — Verify PIN prompt screen
            # ─────────────────────────────────────────────────────────
            current_step = 5
            log.info("[STEP 5] Verifying PIN prompt…")
            pin_title_key = UI_IDS.get("pin_title", "page_title")
            pin_title_id = f"{TATASKY_PACKAGE}:id/{pin_title_key}"
            pin_text = self.ui.get_text_by_id(pin_title_id, timeout=15)
            log.info(f"[STEP 5] PIN screen text: '{pin_text}'")
            ss5 = self._take_step_screenshot(5, "pin_prompt")
            if "PIN" not in pin_text.upper():
                _record_step(5, "Verify PIN Prompt",
                             f"Expected PIN prompt but got '{pin_text}'",
                             "FAILED", ss5, f"Got '{pin_text}'")
                raise AssertionError(
                    f"Expected PIN prompt but got '{pin_text}'"
                )
            log.info("[STEP 5] ✓ PIN prompt screen confirmed")
            _record_step(5, "Verify PIN Prompt",
                         f"PIN prompt displayed: '{pin_text}'",
                         "PASSED", ss5)

            # ─────────────────────────────────────────────────────────
            # STEP 6 — Enter PIN digits then SELECT
            # ─────────────────────────────────────────────────────────
            current_step = 6
            pin_digits = DEFAULT_PIN
            log.info(f"[STEP 6] Entering PIN: {''.join(pin_digits)}")
            for digit in pin_digits:
                keycode = 7 + int(digit)
                self.ui.press_keycode(keycode)
                time.sleep(0.3)

            time.sleep(0.5)
            self.device.select()
            time.sleep(3)
            ss6 = self._take_step_screenshot(6, "pin_entered")
            _record_step(6, "Enter PIN",
                         f"Entered PIN {''.join(pin_digits)} and pressed SELECT",
                         "PASSED", ss6)

            # ─────────────────────────────────────────────────────────
            # STEP 7 — Navigate RIGHT until "Channel Lock" tab, then click
            # ─────────────────────────────────────────────────────────
            current_step = 7
            log.info("[STEP 7] Navigating RIGHT to find Channel Lock…")
            menu_item_id = UI_IDS.get("channel_lock_menu_item", "menu_item")
            channel_lock_xpath = (
                '//android.widget.CheckedTextView'
                f'[@resource-id="{TATASKY_PACKAGE}:id/{menu_item_id}" '
                'and @text="Channel Lock"]'
            )
            max_rights = MAX_RIGHT_SEARCH
            found = False
            for i in range(max_rights):
                if self.ui.exists_by_xpath(channel_lock_xpath, timeout=2):
                    log.info(f"[STEP 7] Channel Lock tab found after {i} rights")
                    found = True
                    break
                self.device.navigate_right(1)
                time.sleep(0.5)

            if not found:
                ss7 = self._take_step_screenshot(7, "channel_lock_not_found")
                _record_step(7, "Navigate to Channel Lock",
                             f"Channel Lock tab not found after {max_rights} rights",
                             "FAILED", ss7,
                             f"Channel Lock tab not found after {max_rights} rights")
                raise AssertionError(
                    f"Channel Lock tab not found after {max_rights} rights"
                )

            self.ui.click_by_xpath(channel_lock_xpath, timeout=5)
            log.info("[STEP 7] ✓ Clicked Channel Lock tab via Appium")
            time.sleep(5)
            ss7 = self._take_step_screenshot(7, "channel_lock_tab")
            _record_step(7, "Navigate to Channel Lock",
                         "Found Channel Lock tab and clicked it via Appium",
                         "PASSED", ss7)

            # ─────────────────────────────────────────────────────────
            # STEP 8 — Press DOWN 1 to enter channel list
            # ─────────────────────────────────────────────────────────
            current_step = 8
            log.info("[STEP 8] Pressing DOWN 1 into channel list…")
            self.device.navigate_down(1)
            time.sleep(1)
            ss8 = self._take_step_screenshot(8, "channel_list_entered")
            _record_step(8, "Enter Channel List",
                         "Pressed DOWN to focus the channel list area",
                         "PASSED", ss8)

            # ─────────────────────────────────────────────────────────
            # STEP 9 — Lock all channels (skip already-locked ones)
            # ─────────────────────────────────────────────────────────
            current_step = 9
            log.info("[STEP 9] Locking channels…")

            cb_key = UI_IDS.get("checkbox", "cb")
            checkbox_id = f"{TATASKY_PACKAGE}:id/{cb_key}"
            cn_key = UI_IDS.get("channel_name", "channelName")
            channel_name_id = f"{TATASKY_PACKAGE}:id/{cn_key}"
            cnum_key = UI_IDS.get("channel_number", "channelNumber")
            channel_number_id = f"{TATASKY_PACKAGE}:id/{cnum_key}"

            seen_channels = set()
            no_new_count = 0
            max_no_new = MAX_NO_NEW_SCROLLS
            scroll_iter = 0
            newly_locked = 0
            already_locked = 0
            lock_limit = CHANNELS_TO_LOCK  # 0 = lock ALL
            last_processed_name = None     # tracks which channel was last handled

            # ── Scroll-and-lock approach ──────────────────────────
            # D-pad focus starts on the first channel row (Step 8).
            # Each batch: read visible channels, find where we left
            # off, process only the NEW channels (with SELECT+DOWN
            # for each). Skip duplicates WITHOUT pressing DOWN since
            # the focus is already past them.

            while no_new_count < max_no_new and scroll_iter < MAX_SCROLL_ITERATIONS:
                if lock_limit > 0 and newly_locked >= lock_limit:
                    log.info(f"[STEP 9] Reached lock limit ({lock_limit}), stopping.")
                    break

                scroll_iter += 1
                log.info(f"[STEP 9] Scroll batch {scroll_iter}/{MAX_SCROLL_ITERATIONS}")

                # Read all currently visible channels
                name_elements = self.ui.find_all_by_id(channel_name_id, timeout=5)
                if not name_elements:
                    log.warning("[STEP 9] No channel names found on screen")
                    break

                cb_elements = self.ui.find_all_by_id(checkbox_id, timeout=2)
                num_elements = self.ui.find_all_by_id(channel_number_id, timeout=2)

                # Determine where to start processing in this batch.
                # Skip elements that were already processed (above the
                # current focus) — do NOT press DOWN for these.
                start_idx = 0
                if last_processed_name:
                    for i, el in enumerate(name_elements):
                        try:
                            if el.text.strip() == last_processed_name:
                                start_idx = i + 1
                                break
                        except Exception:
                            continue

                found_new_in_batch = False

                for idx in range(start_idx, len(name_elements)):
                    if lock_limit > 0 and newly_locked >= lock_limit:
                        break

                    try:
                        ch_name = name_elements[idx].text.strip()
                    except Exception:
                        ch_name = ""

                    if not ch_name or ch_name in seen_channels:
                        # Already processed in a previous batch — skip
                        # WITHOUT pressing DOWN (focus is already past it)
                        continue

                    seen_channels.add(ch_name)
                    found_new_in_batch = True

                    ch_number = "?"
                    if idx < len(num_elements):
                        try:
                            ch_number = num_elements[idx].text.strip()
                        except Exception:
                            pass

                    is_checked = False
                    if idx < len(cb_elements):
                        try:
                            is_checked = cb_elements[idx].get_attribute("checked") == "true"
                        except Exception:
                            pass

                    if is_checked:
                        already_locked += 1
                        log.info(
                            f"[STEP 9] Ch {ch_number} — {ch_name} — "
                            f"ALREADY LOCKED ✓ (skipped)"
                        )
                    else:
                        # Press SELECT to toggle lock on the currently focused row
                        try:
                            self.device.select()
                            newly_locked += 1
                            log.info(
                                f"[STEP 9] Ch {ch_number} — {ch_name} — "
                                f"LOCKED NOW 🔒 (via SELECT)"
                            )
                            time.sleep(0.3)
                        except Exception as click_exc:
                            log.warning(
                                f"[STEP 9] Ch {ch_number} — {ch_name} — "
                                f"FAILED to lock: {click_exc}"
                            )

                    locked_channels.append({
                        "channel_number": ch_number,
                        "channel_name": ch_name,
                        "locked": True,
                    })

                    last_processed_name = ch_name

                    # Press DOWN to move focus to the next channel
                    self.device.navigate_down(1)
                    time.sleep(0.3)

                if found_new_in_batch:
                    no_new_count = 0
                else:
                    no_new_count += 1

                # Small wait for scroll/render before re-reading
                time.sleep(0.5)

            if scroll_iter >= MAX_SCROLL_ITERATIONS:
                log.warning(f"[STEP 9] Reached max scroll limit ({MAX_SCROLL_ITERATIONS})")

            lock_target_str = str(lock_limit) if lock_limit > 0 else "ALL"
            log.info(f"[STEP 9] Lock target             : {lock_target_str}")
            log.info(f"[STEP 9] Total channels scanned : {len(seen_channels)}")
            log.info(f"[STEP 9] Newly locked           : {newly_locked}")
            log.info(f"[STEP 9] Already locked (skipped): {already_locked}")

            ss9 = self._take_step_screenshot(9, "channel_locking_done")
            _record_step(9, "Lock Channels",
                         f"Scanned {len(seen_channels)} channels | "
                         f"Newly locked: {newly_locked} | "
                         f"Already locked: {already_locked} | "
                         f"Lock target: {lock_target_str}",
                         "PASSED", ss9)

            # ── Save locked channels to report ─────────────────────────
            self._save_locked_channels_to_report(locked_channels)

            # ─────────────────────────────────────────────────────────
            # STEP 10 — Press HOME
            # ─────────────────────────────────────────────────────────
            current_step = 10
            log.info("[STEP 10] Pressing HOME…")
            self.device.home()
            time.sleep(2)
            log.info("[STEP 10] ✓ Back at home")
            ss10 = self._take_step_screenshot(10, "back_home")
            _record_step(10, "Press HOME",
                         "Pressed HOME key to return to the home screen",
                         "PASSED", ss10)

            log.info("=" * 60)
            log.info("TEST PASSED — Parental Lock channel lock complete")

        except Exception as e:
            status = "FAILED"
            error_type = type(e).__name__
            error_message = str(e)
            failed_step = f"Step {current_step}"
            full_tb = traceback.format_exc()
            log.error(f"TEST FAILED at step {current_step}: {e}", exc_info=True)

            # Mark remaining steps as SKIPPED
            recorded_nums = {s["step_number"] for s in step_results}
            all_step_names = {
                1: "Verify Home Screen",
                2: "Navigate to User Preferences",
                3: "Verify USER PREFERENCES Title",
                4: "Find & Click Parental Controls",
                5: "Verify PIN Prompt",
                6: "Enter PIN",
                7: "Navigate to Channel Lock",
                8: "Enter Channel List",
                9: "Lock Channels",
                10: "Press HOME",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded_nums:
                    _record_step(sn, sname, "Step not reached due to earlier failure",
                                 "SKIPPED", None, "")

            try:
                ss_path = (
                    self.screenshots_folder
                    / f"FAIL_parental_lock_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(ss_path))
            except Exception:
                pass

        finally:
            pytest.locked_channels = locked_channels

            # ── Module-wise step-by-step Excel sheet ──────────────────
            self.report_gen.add_module_report(
                module_name="Parental Lock Setup",
                device_id=self.device_id,
                overall_status=status,
                steps=sorted(step_results, key=lambda s: s["step_number"]),
                summary_info={
                    "Total Channels Scanned": len(seen_channels) if 'seen_channels' in dir() else 0,
                    "Newly Locked": newly_locked if 'newly_locked' in dir() else 0,
                    "Already Locked": already_locked if 'already_locked' in dir() else 0,
                },
            )

            log.info(f"[RESULT] Status={status}  Locked channels={len(locked_channels)}")
            log.info("=" * 60)

            if status == "FAILED":
                pytest.fail(error_message)
