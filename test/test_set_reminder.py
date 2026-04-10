import pytest
import time
import os
import logging
import traceback
from pathlib import Path
import yaml
import random

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
log = logging.getLogger("TestSetRemindersSetup")

# ─── Load settings ───────────────────────────────────────────────────────────
with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)

LOGO_DIR = Path("libraries/Screenshots_AppLogo")

# ─── Set Reminder config from settings.yaml ────────────────────────────────
PL_CFG = SETTINGS.get("parental_lock", {})
TATASKY_PACKAGE = PL_CFG.get("app_package", "tv.accedo.studio.paytv.tatasky")
HOME_CFG = PL_CFG.get("home_check", {})
UI_IDS = PL_CFG.get("ui_ids", {})


class TestSetReminderSetup:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with ADB device + Appium session"""
        log.info("=" * 60)
        log.info("SETUP — Set Reminder test initialisation")

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

    def _save_reminders_to_report(self, reminders):
        """Add reminders as a sheet in the main report Excel."""
        try:
            self.report_gen.reminders_sheet(reminders)
            log.info(f"[EXCEL] reminders list sheet added to report ({len(reminders)} reminders)")
            log.info(f"[REMINDERS LIST] Total: {len(reminders)}")
        except Exception as e:
            log.warning(f"[EXCEL] Failed to save Reminders List: {e}")

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

    def test_set_reminders(self, request):
        """
        Set Reminder Setup — navigate to guide, set reminders on future events.
        If SNS appears while setting any reminder → retry the entire test from Step 1.
        """
        reminders = []
        step_results = []

        status = "PASSED"
        error_message = ""
        current_step = 0

        # Common IDs
        dismiss_id = 'tv.accedo.studio.paytv.tatasky:id/dismissButton'
        SNS_id = 'tv.accedo.studio.paytv.tatasky:id/infobar_base_layout'

        # Home screen config
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

        MAX_RETRIES = 3

        for retry in range(MAX_RETRIES):
            try:
                log.info(f"\n{'='*70}")
                log.info(f"[RETRY {retry+1}/{MAX_RETRIES}] Starting Set Reminders Test")
                reminders.clear()
                step_results.clear()
                count = 0   # Number of successfully set reminders

                # ─────────────────────────────────────────────────────────
                # STEP 1 — Verify Home Screen
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
                        log.warning(f"[STEP 1] Home not detected (attempt {attempt}), pressing HOME")
                        self.device.home()
                        time.sleep(2)

                ss1 = self._take_step_screenshot(1, "home_screen")
                if not home_detected:
                    _record_step(1, "Verify Home Screen",
                                 f"Home logo not detected after {hc_max} attempts", "FAILED", ss1)
                    raise AssertionError("Home screen not detected")

                _record_step(1, "Verify Home Screen",
                             "Home screen confirmed via logo", "PASSED", ss1)

                # ─────────────────────────────────────────────────────────
                # STEP 2 — Navigate to TV Channels
                # ─────────────────────────────────────────────────────────
                current_step = 2
                TV = '//android.widget.CheckedTextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/menu_item" and @text="TV Channels"]'
                log.info("[STEP 2] Navigating to TV Channels")

                if self.ui.exists_by_xpath(TV):
                    self.ui.click_by_xpath(TV)
                    ss2 = self._take_step_screenshot(2, "TV_Channels_nav")
                    _record_step(2, "Navigate to TV Channels", "TV Channels tab selected", "PASSED", ss2)
                else:
                    if self.ui.exists_by_id(dismiss_id):
                        self.ui.click_by_id(dismiss_id)
                        raise Exception("Previous Reminder banner detected")
                    ss2 = self._take_step_screenshot(2, "TV_Channels_failed")
                    _record_step(2, "Navigate to TV Channels", "TV Channels tab not found", "FAILED", ss2)
                    raise AssertionError("TV Channels tab not found")

                time.sleep(3)

                # ─────────────────────────────────────────────────────────
                # STEP 3 — Launch Guide
                # ─────────────────────────────────────────────────────────
                current_step = 3
                guide_xpath = '//android.widget.CheckedTextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/menu_item" and @text="Guide"]'
                log.info("[STEP 3] Launching Guide")

                if self.ui.exists_by_xpath(guide_xpath):
                    self.ui.click_by_xpath(guide_xpath)
                    time.sleep(2)
                    ss3 = self._take_step_screenshot(3, "Guide_launched")
                    _record_step(3, "Launch Guide", "Guide launched successfully", "PASSED", ss3)
                else:
                    if self.ui.exists_by_id(dismiss_id):
                        self.ui.click_by_id(dismiss_id)
                        raise Exception("Previous Reminder banner detected")
                    ss3 = self._take_step_screenshot(3, "Guide_failed")
                    _record_step(3, "Launch Guide", "Guide not found", "FAILED", ss3)
                    raise AssertionError("Guide not launched")

                # ─────────────────────────────────────────────────────────
                # STEP 4 — Launch All Channels Guide
                # ─────────────────────────────────────────────────────────
                current_step = 4
                log.info("[STEP 4] Launching All Channels Guide")
                self.device.select()
                self.device.select()
                time.sleep(3)

                if self.ui.exists_by_id(dismiss_id):
                    self.ui.click_by_id(dismiss_id)
                    raise Exception("Previous Reminder banner detected")

                Filter_xpath = '//android.widget.TextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/textViewFilter"]'
                title_text = self.ui.get_text_by_xpath(Filter_xpath, timeout=10)

                if title_text != "Filter : ALL CHANNELS":
                    ss4 = self._take_step_screenshot(4, "AllChannels_failed")
                    _record_step(4, "Launch All Channels Guide", "All Channels Guide not launched", "FAILED", ss4)
                    raise AssertionError("All Channels Guide not launched")

                ss4 = self._take_step_screenshot(4, "AllChannels_found")
                _record_step(4, "Launch All Channels Guide", "All Channels Guide launched", "PASSED", ss4)

                # ─────────────────────────────────────────────────────────
                # STEP 5 — Set 6 Reminders (SNS will trigger full retry)
                # ─────────────────────────────────────────────────────────
                current_step = 5
                log.info("[STEP 5] Starting to set 6 reminders...")

                reminder_icon_xpath = '//android.widget.ImageView[@resource-id="tv.accedo.studio.paytv.tatasky:id/imageViewReminderIcon"]'
                Highlighted_EPG = '(//android.widget.TextView[@resource-id="tv.accedo.studio.paytv.tatasky:id/textView"])[8]'
                Set_reminder_xpath = '//android.widget.Button[@text="SET REMINDER"]'
                name_id = 'tv.accedo.studio.paytv.tatasky:id/textViewTitle'
                channel_number_id = 'tv.accedo.studio.paytv.tatasky:id/textViewDescriptionHeader'
                Time_ID = 'tv.accedo.studio.paytv.tatasky:id/textViewStartEndTime'

                while count < 6:
                    # Check for reminder banner
                    if self.ui.exists_by_id(dismiss_id):
                        self.ui.click_by_id(dismiss_id)
                        raise Exception("Previous Reminder banner detected")

                    max_downs = random.randint(5, 15)
                    max_right = random.randint(1, 2)

                    self.device.navigate_down(max_downs)
                    self.device.navigate_right(max_right)
                    time.sleep(1.5)

                    EPG_text = self.ui.get_text_by_xpath(Highlighted_EPG, timeout=8)

                    # Only proceed if we have valid event and no reminder already set
                    if EPG_text == "No information" or self.ui.exists_by_xpath(reminder_icon_xpath, timeout=2):
                        self.device.left(max_right)
                        continue

                    log.info(f"[STEP 5] Attempting to set reminder {count + 1}/6")

                    self.device.select()
                    time.sleep(2.5)

                    # ================== CRITICAL SNS CHECK ==================
                    if self.ui.exists_by_id(SNS_id, timeout=4):
                        log.warning("[SNS DETECTED] While setting reminder → Retrying entire test from Step 1")
                        self.device.home()
                        time.sleep(2)
                        raise Exception("SNS_INTERRUPT_RETRY_ALL")

                    # Check banner again
                    if self.ui.exists_by_id(dismiss_id):
                        self.ui.click_by_id(dismiss_id)
                        raise Exception("Previous Reminder banner detected")

                    # Set Reminder
                    if self.ui.exists_by_xpath(Set_reminder_xpath, timeout=5):
                        self.ui.click_by_xpath(Set_reminder_xpath)
                        log.info(f"[STEP 5] ✓ Reminder {count + 1} set successfully")

                        channel_name = self.ui.get_text_by_id(name_id, timeout=8)
                        channel_desc = self.ui.get_text_by_id(channel_number_id, timeout=8)
                        event_time = self.ui.get_text_by_id(Time_ID, timeout=8)

                        reminders.append({
                            "event_name": channel_name,
                            "channel_description": channel_desc,
                            "Time": event_time,
                        })

                        count += 1
                        self.device.back()
                        time.sleep(1.5)
                        self.device.left(max_right)
                    else:
                        self.device.back()   # close any unexpected popup
                        time.sleep(1)

                # Success - 6 reminders set
                ss5 = self._take_step_screenshot(5, "set_reminders_success")
                _record_step(5, "Set 6 Reminders",
                             f"Successfully set {len(reminders)} reminders", "PASSED", ss5)

                # ─────────────────────────────────────────────────────────
                # STEP 6 — Press HOME
                # ─────────────────────────────────────────────────────────
                current_step = 6
                log.info("[STEP 6] Pressing HOME")
                self.device.home()
                time.sleep(2)
                ss6 = self._take_step_screenshot(6, "back_home")
                _record_step(6, "Press HOME", "Returned to home screen", "PASSED", ss6)

                log.info("TEST PASSED — 6 Reminders set successfully")
                break  # Exit retry loop

            except Exception as e:
                if "SNS_INTERRUPT_RETRY_ALL" in str(e):
                    log.info(f"SNS detected - Retrying from beginning (attempt {retry+1})")
                    if retry == MAX_RETRIES - 1:
                        status = "FAILED"
                        error_message = "SNS kept appearing even after maximum retries"
                    continue
                else:
                    # Other failures
                    status = "FAILED"
                    error_message = str(e)
                    log.error(f"Test failed at step {current_step}: {e}", exc_info=True)
                    break

        # ===================== FINAL REPORTING =====================
        self._save_reminders_to_report(reminders)

        # Mark unexecuted steps as SKIPPED if failed
        if status == "FAILED":
            recorded = {s["step_number"] for s in step_results}
            all_step_names = {
                1: "Verify Home Screen",
                2: "Navigate to TV Channels",
                3: "Launch Guide",
                4: "Launch All Channels Guide",
                5: "Set Reminders",
                6: "Press HOME",
            }
            for sn, sname in all_step_names.items():
                if sn not in recorded:
                    _record_step(sn, sname, "Step not reached due to earlier failure", "SKIPPED")

        self.report_gen.add_module_report(
            module_name="Set Reminder Setup",
            device_id=self.device_id,
            overall_status=status,
            steps=sorted(step_results, key=lambda s: s["step_number"]),
        )

        log.info(f"[RESULT] Status = {status} | Reminders Set = {len(reminders)}")
        log.info("=" * 70)

        if status == "FAILED":
            pytest.fail(error_message)