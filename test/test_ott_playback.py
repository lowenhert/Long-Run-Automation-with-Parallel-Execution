import random
import pytest
import time
import os
import logging
import re
import traceback
from pathlib import Path
import re
import yaml


class BlackScreenFailure(Exception):
    """Raised when black-screen checks fail — NOT caught by the AssertionError handler
    so the finally block still runs, the result is recorded, and pytest moves on
    to the next parametrized app automatically."""
    pass


class HomeScreenFailure(Exception):
    """Raised when home screen is detected during playback — app crashed back to home.
    We don't need to press back since we're already at home."""
    pass


from core.device_manager import DeviceManager
from core.report_manager import ReportGenerator
from libraries.DeviceController import DeviceController
from libraries.BlackScreenCheck import BlackScreenCheck
from libraries.OcrLibrary import OcrLibrary
from libraries.LogoCompareLibrary import LogoCompareLibrary

# ─── Logger setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("TestOTTPlayback")


# ─────────────────────────────────────────────────────────────────────────────


# Load config
def load_test_cases():
    """Load test cases from config, with support for dynamic selection - NON-DRM ONLY"""
    selected_cases_file = os.getenv('SELECTED_CASES_FILE')
    if selected_cases_file and Path(selected_cases_file).exists():
        log.debug(f"Loading test cases from SELECTED_CASES_FILE: {selected_cases_file}")
        with open(selected_cases_file) as f:
            all_cases = yaml.safe_load(f)["test_cases"]
            # Filter for non-DRM apps only
            return [case for case in all_cases if not case.get("drm", False)]

    current_test_index = os.getenv('CURRENT_TEST_CASE')
    if current_test_index is not None:
        log.debug(f"Loading single test case at index {current_test_index}")
        with open("config/test_cases.yaml") as f:
            all_cases = yaml.safe_load(f)["test_cases"]
        try:
            index = int(current_test_index)
            if 0 <= index < len(all_cases) and not all_cases[index].get("drm", False):
                return [all_cases[index]]
        except (ValueError, IndexError):
            log.warning(f"Invalid CURRENT_TEST_CASE index: {current_test_index}, falling back to non-DRM cases")

    log.debug("Loading non-DRM test cases from config/test_cases.yaml")
    with open("config/test_cases.yaml") as f:
        all_cases = yaml.safe_load(f)["test_cases"]
        # Filter for non-DRM apps only
        non_drm_cases = [case for case in all_cases if not case.get("drm", False)]
        return non_drm_cases


TEST_CASES = load_test_cases()
log.info(f"Loaded {len(TEST_CASES)} test case(s)")

with open("config/settings.yaml") as f:
    SETTINGS = yaml.safe_load(f)
log.debug(f"Settings loaded: {SETTINGS}")

# ─── Logo directory path ─────────────────────────────────────────────────────
LOGO_DIR = Path("libraries/Screenshots_AppLogo")


# ─────────────────────────────────────────────────────────────────────────────


def verify_app_launch_ocr(ocr_lib: OcrLibrary, screenshot_bytes: bytes,
                          expected_text: str, region: tuple = (80, 164, 271, 90)) -> bool:
    x, y, width, height = region
    log.info(f"[OCR VERIFY] Checking region ({x}, {y}, {width}, {height}) for: '{expected_text}'")

    extracted_text = ocr_lib.extract_text_from_region_bytes(screenshot_bytes, x, y, width, height)
    log.debug(f"[OCR VERIFY] Extracted text: '{extracted_text}'")

    if expected_text.lower() not in extracted_text.lower():
        msg = f"OCR verification failed. Expected '{expected_text}' not found in '{extracted_text}'"
        log.error(f"[OCR VERIFY] ❌ {msg}")
        raise AssertionError(msg)

    log.info(f"[OCR VERIFY] ✓ Found '{expected_text}' in extracted text")
    return True


def verify_app_launch_logo(logo_lib: LogoCompareLibrary, screenshot_bytes: bytes,
                           logo_file: str, region: tuple = (80, 164, 271, 90),
                           threshold: float = 0.80) -> bool:
    logo_path = LOGO_DIR / logo_file
    x, y, width, height = region

    log.info(f"[LOGO VERIFY] Checking region ({x}, {y}, {width}, {height}) for logo: '{logo_file}'")
    log.debug(f"[LOGO VERIFY] Full logo path: {logo_path}")

    if not logo_path.exists():
        msg = f"Logo file not found: {logo_path}"
        log.error(f"[LOGO VERIFY] ❌ {msg}")
        raise AssertionError(msg)

    logo_lib.fail_if_logo_not_present_bytes(
        screenshot_bytes, str(logo_path), x, y, width, height, threshold
    )

    log.info(f"[LOGO VERIFY] ✓ Logo '{logo_file}' detected successfully")
    return True


def verify_app_launch(test_case: dict, ocr_lib: OcrLibrary, logo_lib: LogoCompareLibrary,
                      screenshot_bytes: bytes, region: tuple = (80, 164, 271, 90)) -> bool:
    verification_type = test_case.get("verification_type", "ocr").lower()
    app_name = test_case.get("app_name", "Unknown")

    log.info(f"[VERIFY] Starting {verification_type.upper()} verification for '{app_name}'")

    if verification_type == "logo":
        logo_file = test_case.get("logo_file")
        if not logo_file:
            log.warning(f"[VERIFY] No logo_file specified for '{app_name}', falling back to OCR")
            verification_type = "ocr"
        else:
            return verify_app_launch_logo(logo_lib, screenshot_bytes, logo_file, region)

    if verification_type == "ocr":
        expected_text = test_case.get("expected_ocr_text", app_name)
        return verify_app_launch_ocr(ocr_lib, screenshot_bytes, expected_text, region)

    # Unknown verification type - default to OCR
    log.warning(f"[VERIFY] Unknown verification_type '{verification_type}', defaulting to OCR")
    expected_text = test_case.get("expected_ocr_text", app_name)
    return verify_app_launch_ocr(ocr_lib, screenshot_bytes, expected_text, region)


class TestOTTPlayback:

    @pytest.fixture(scope="function", autouse=True)
    def setup(self, request):
        """Setup test environment with proper device isolation"""
        log.info("=" * 60)
        log.info("SETUP — starting test environment initialisation")

        # Resolve device ID
        self.device_id = (
                os.getenv("DEVICE_ID")
                or os.getenv("DEVICE_NAME")
                or os.getenv("TARGET_DEVICE")
        )
        if not self.device_id:
            log.warning("No DEVICE_ID env var found — falling back to first connected device")
            self.device_id = DeviceManager.get_connected_devices()[0]

        log.info(f"🎯 Using device: {self.device_id}")

        log.debug("Initialising DeviceController…")
        self.device = DeviceController(self.device_id)
        log.debug("DeviceController OK")

        log.debug("Initialising BlackScreenCheck…")
        self.black_screen_checker = BlackScreenCheck(
            screenshot_dir="./screenshots",
            device_name=self.device_id
        )
        log.debug("BlackScreenCheck OK")

        log.debug(f"Initialising OcrLibrary (tesseract_path={SETTINGS.get('tesseract_path')})…")
        self.ocr = OcrLibrary(SETTINGS.get("tesseract_path"))
        log.debug("OcrLibrary OK")

        log.debug("Initialising LogoCompareLibrary…")
        self.logo_compare = LogoCompareLibrary()
        log.debug("LogoCompareLibrary OK")

        log.debug("Initialising ReportGenerator…")
        self.report_gen = ReportGenerator(request.node.execution_dir)
        log.debug("ReportGenerator OK")

        log.info("SETUP complete")
        yield
        self._cleanup()

    def _cleanup(self):
        """Cleanup after test"""
        log.info(f"🧹 CLEANUP — navigating home on device {self.device_id}")
        try:
            self.device.home()
            time.sleep(2)
            log.info("CLEANUP complete")
        except Exception as e:
            log.error(f"CLEANUP failed: {e}", exc_info=True)

    @pytest.mark.parametrize("test_case", TEST_CASES)
    def test_ott_playback(self, test_case, request):
        """Main test – fully configurable per device with retry logic for full app failure"""
        app_name = test_case["app_name"]
        screenshots_folder = request.node.screenshot_dir
        max_app_retries = 3  # Retry entire app if ALL contents fail

        log.info("=" * 60)
        log.info(f"TEST START — app={app_name}  device={self.device_id}")
        log.debug(f"Full test_case config: {test_case}")

        for app_attempt in range(1, max_app_retries + 1):
            if app_attempt > 1:
                log.info(f"[RETRY] App attempt {app_attempt}/{max_app_retries} for {app_name}")
                # Go home, navigate down 2x to reach apps row, then select current app
                self.device.home()
                time.sleep(2)
                self.device.navigate_down(2)
                time.sleep(0.5)
                self.device.select()
                log.info("[RETRY] Waiting 8 s for app to reload…")
                time.sleep(8)
                
                # Verify app launched after retry
                try:
                    screenshot_bytes = self.device.take_screenshot_bytes()
                    verify_app_launch(test_case=test_case, ocr_lib=self.ocr, logo_lib=self.logo_compare, 
                                      screenshot_bytes=screenshot_bytes, region=(80, 164, 271, 90))
                    log.info(f"[RETRY] ✓ {app_name} relaunched successfully")
                except Exception as retry_launch_exc:
                    log.error(f"[RETRY] App relaunch failed: {retry_launch_exc}")
                    if app_attempt == max_app_retries:
                        # Final attempt failed
                        self.report_gen.add_result(
                            app_name=app_name, content_name="App Retry Launch Failed", playback_time=0,
                            device_id=self.device_id, status="FAILED",
                            screenshots_folder=str(screenshots_folder),
                            error_type=type(retry_launch_exc).__name__,
                            error_message=str(retry_launch_exc),
                            failed_step="App Retry Launch",
                            full_traceback=traceback.format_exc(),
                        )
                        log.error(f"TEST FAILED — {app_name} could not relaunch after {max_app_retries} attempts")
                        log.info("=" * 60)
                        raise
                    continue  # Try next attempt

            # Track results for this attempt
            content_results = []  # List of True (pass) / False (fail) for each content

            # First attempt - do full navigation
            if app_attempt == 1:
                try:
                    down = test_case["navigation"]["down_presses"]
                    right = test_case["navigation"]["right_presses"]
                    log.info(f"[NAVIGATION] Pressing DOWN x{down}, RIGHT x{right}")
                    self.device.navigate_down(down)
                    self.device.navigate_right(right)
                    self.device.select()

                    log.info("[NAVIGATION] Waiting 8 s for app to load…")
                    time.sleep(8)

                    screenshot_bytes = self.device.take_screenshot_bytes()
                    verify_app_launch(test_case=test_case,ocr_lib=self.ocr,logo_lib=self.logo_compare,screenshot_bytes=screenshot_bytes,region=(80, 164, 271, 90))
                    log.info(f"[APP LAUNCH] ✓ {app_name} launched successfully")

                except Exception as launch_exc:
                    # App didn't launch — log and retry if attempts remain
                    log.error(f"[APP LAUNCH] ❌ Failed to launch {app_name} (attempt {app_attempt}): {launch_exc}", exc_info=True)
                    
                    if app_attempt < max_app_retries:
                        log.info(f"[RETRY] Will retry app {app_name} (attempt {app_attempt + 1}/{max_app_retries})")
                        continue  # Retry the app
                    
                    # Final attempt failed - record and bail
                    try:
                        failure_ss_path = (
                                screenshots_folder
                                / f"LAUNCH_FAIL_{app_name}_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                        )
                        self.device.take_screenshot(str(failure_ss_path))
                    except Exception:
                        pass

                    self.report_gen.add_result(app_name=app_name,content_name="App Launch Failed",playback_time=0,device_id=self.device_id,
                        status="FAILED",
                        screenshots_folder=str(screenshots_folder),
                        error_type=type(launch_exc).__name__,
                        error_message=str(launch_exc),
                        failed_step="App Launch",
                        full_traceback=traceback.format_exc(),
                    )
                    log.error(f"TEST FAILED — {app_name} could not launch after {max_app_retries} attempts")
                    log.info("=" * 60)
                    raise

            num_contents = test_case.get("random_content_plays", 2)
            max_cycle_retries = 3   # Restart full content sequence from content 1 on any failure
            cycle_at_home = False   # Tracks if last failure left us at home screen

            for cycle_attempt in range(1, max_cycle_retries + 1):
                cycle_content_failed = False  # Set True when a content fails → triggers restart from content 1

                if cycle_attempt > 1:
                    log.info(
                        f"[CYCLE RETRY {cycle_attempt}/{max_cycle_retries}] "
                        f"Restarting from content 1 for {app_name}"
                    )
                    if cycle_at_home:
                        log.info("[CYCLE RETRY] App at home — re-launching directly")
                        self.device.navigate_down(2)
                        time.sleep(0.5)
                        self.device.select()
                        log.info("[CYCLE RETRY] Waiting 8s for app to reload…")
                        time.sleep(8)
                        cycle_at_home = False
                    else:
                        self.device.back()
                        time.sleep(1)
                        self.device.back()
                        time.sleep(1)

                for content_num in range(1, num_contents + 1):
                    max_content_retries = 3
                    already_at_home = False  # True after app crashes to home; skip home press on re-launch

                    for content_attempt in range(1, max_content_retries + 1):
                        # Per-attempt result variables — reset each retry
                        content_name = test_case.get("content_name_fallback", app_name)
                        status = "PASSED"
                        error_type = ""
                        error_message = ""
                        failed_step = ""
                        full_traceback = ""
                        _should_retry = False  # Set True in HomeScreenFailure handler to trigger a re-launch retry

                        log.info("-" * 60)
                        log.info(
                            f"[CONTENT {content_num}/{num_contents}] "
                            f"(App {app_attempt}/{max_app_retries}, Content attempt {content_attempt}/{max_content_retries}) "
                            f"Starting random content selection"
                        )

                        # ── Re-launch app on retry ────────────────────────────────
                        if content_attempt > 1:
                            if already_at_home:
                                # App already crashed back to home — navigate directly without pressing home again
                                log.info(
                                    f"[CONTENT {content_num}] Already at home — re-launching app without pressing home"
                                )
                                self.device.navigate_down(2)
                                time.sleep(0.5)
                                self.device.select()
                                log.info("[CONTENT RETRY] Waiting 8s for app to reload…")
                                time.sleep(8)
                                already_at_home = False
                            else:
                                log.info(f"[CONTENT {content_num}] Navigating back to content selection screen")
                                self.device.back()
                                time.sleep(1)
                                self.device.back()
                                time.sleep(1)

                        try:
                            resume_region = test_case.get("resume_region")
                            rx, ry, rw, rh = resume_region
                            for i in range(10):

                                # ── Random navigation to pick content ────────────────────
                                rand_down = random.randint(0, 5)
                                rand_right = random.randint(1, 5)
                                log.info(f"[RANDOM NAV] DOWN x{rand_down}, RIGHT x{rand_right}")
                                self.device.navigate_down(rand_down)
                                time.sleep(0.5)
                                self.device.navigate_right(rand_right)
                                time.sleep(1)

                                log.info("[PLAYBACK] Pressing select() to choose content")
                                self.device.select()
                                time.sleep(5)

                                # check resume content
                                screenshot_bytes = self.device.take_screenshot_bytes()
                                resume = self.ocr.extract_text_from_region_bytes(screenshot_bytes, rx, ry, rw,
                                                                                 rh).strip()
                                resume = re.sub(r'[^A-Za-z0-9 ]', '', resume).replace(" ", "_")
                                if "RESUME" not in resume and "REPLAY" not in resume:

                                    # ── OCR title of selected content ────────────────────────
                                    screenshot_bytes = self.device.take_screenshot_bytes()
                                    title_text = self.ocr.extract_text_from_region_bytes(
                                        screenshot_bytes, 80, 156, 1022 - 80, 223 - 156
                                    ).strip()
                                    title_text = re.sub(r'[^A-Za-z0-9 ]', '', title_text).replace(" ", "_")
                                    if title_text:
                                        content_name = title_text.replace("_", " ").title()
                                    else:
                                        title_text = content_name.replace(" ", "_")
                                    log.info(f"[OCR] Content {content_num}: '{content_name}'")

                                    # ── Screenshot of selected content ───────────────────────
                                    selected_ss_path = (
                                            screenshots_folder
                                            / f"content{content_num}_selected_{app_name}_{title_text}_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                                    )
                                    log.info(f"[SCREENSHOT] Saving selected screen → {selected_ss_path}")
                                    self.device.take_screenshot(str(selected_ss_path))

                                    break

                                else:
                                    log.info("Resume content detected, pressing back to play a new content")
                                    self.device.back()

                            # ── Start playback ───────────────────────────────────────
                            log.info("[PLAYBACK] Pressing select() to start video")
                            self.device.select()
                       
                            # Wait longer for playback to start, then long-press right to skip any intros or ads
                            end_time=time.time()+30
                            while time.time() < end_time:
                                self.device.long_press_right()
                                time.sleep(0.3)

                            time.sleep(5)
                            log.info("[PLAYBACK] Initial wait complete, starting monitoring…")
                        
                            playback_duration = test_case.get("playback_duration", SETTINGS.get("playback_duration", 30))
                            log.info(f"[PLAYBACK] Monitoring for {playback_duration} seconds")

                            check_interval = SETTINGS["check_interval"]
                            black_pct = SETTINGS["black_percentage"]
                            num_checks = max(1, playback_duration // check_interval)
                            black_screen_failures = []

                            log.info(
                                f"[BLACK_SCREEN + SS] Performing {num_checks} checks "
                                f"(interval={check_interval}s, black threshold={black_pct}%)"
                            )

                            playback_start = time.time()
                            playback_end = playback_start + playback_duration

                            for i in range(num_checks):
                                if time.time() >= playback_end:
                                    log.debug(f"[WAIT] Playback duration ended before check {i + 1} — skipping remaining checks")
                                    break
                                target_check_time = playback_start + (i + 1) * check_interval
                                sleep_needed = target_check_time - time.time()
                                if sleep_needed > 0:
                                    log.debug(f"[WAIT] Sleeping {sleep_needed:.2f}s before check {i + 1}/{num_checks}")
                                    time.sleep(sleep_needed)
                                else:
                                    log.debug(
                                        f"[WAIT] Check {i + 1} already overdue by {-sleep_needed:.2f}s — proceeding immediately"
                                    )

                                check_ss_name = (
                                    f"c{content_num}_playback_check_{i + 1:02d}_{app_name}_{title_text}_"
                                    f"t{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                                )
                                check_ss_path = screenshots_folder / check_ss_name

                                # ── Capture screenshot ───────────────────────────────
                                ss_start = time.time()
                                try:
                                    screenshot_bytes = self.device.take_screenshot_bytes()
                                    log.debug(f"[BLACK_SCREEN] Capture took {time.time() - ss_start:.2f}s")
                                except Exception as ss_exc:
                                    log.warning(f"[BLACK_SCREEN] Check {i + 1} screenshot failed: {ss_exc} — skipping")
                                    continue

                                # ── Black screen check ───────────────────────────────
                                check_file = f"c{content_num}_{app_name}_check_{i}_{self.device_id.replace(':', '_')}.png"
                                try:
                                    self.black_screen_checker.check_black_screen(check_file, black_pct)
                                    log.debug(f"[BLACK_SCREEN] Check {i + 1}/{num_checks} → OK")
                                except Exception as bsc_exc:
                                    log.warning(f"[BLACK_SCREEN] Check {i + 1} failed, retrying…")
                                    time.sleep(1.0)
                                    try:
                                        self.black_screen_checker.check_black_screen(f"{check_file}_retry", black_pct)
                                        log.debug(f"[BLACK_SCREEN] Check {i + 1} → OK (retry)")
                                    except Exception as retry_exc:
                                        with open(check_ss_path, "wb") as f:
                                            f.write(screenshot_bytes)
                                        black_screen_failures.append({
                                            "check_number": i + 1,
                                            "error": str(retry_exc),
                                            "screenshot": str(check_ss_path),
                                        })
                                        log.error(f"[BLACK_SCREEN] Check {i + 1} FAILED after retry (continuing): {retry_exc}",
                                                  exc_info=True)

                                # ── TataPlay logo check ──────────────────────────────
                                TP_logo_path = LOGO_DIR / "TP_logo.png"
                                if TP_logo_path.exists():
                                    log.debug(f"[TATAPLAY CHECK] Check {i + 1}")
                                    try:
                                        self.logo_compare.fail_if_logo_present_bytes(
                                            screenshot_bytes, str(TP_logo_path),
                                            x=80, y=52, width=250, height=78
                                        )
                                    except AssertionError:
                                        with open(check_ss_path, "wb") as f:
                                            f.write(screenshot_bytes)
                                        status = "FAILED"
                                        failed_step = "TataPlay Logo Detection"
                                        error_type = "TataPlayDetected"
                                        error_message = f"TataPlay logo detected at check {i + 1} for {app_name} on {self.device_id}, content not playing"
                                        full_traceback = traceback.format_exc()
                                        log.error(f"[TATAPLAY] ❌ {error_message}")
                                        raise

                                # ── NoSignal logo check ──────────────────────────────
                                nosignal_logo_path = LOGO_DIR / "NoSignal.png"
                                if nosignal_logo_path.exists():
                                    log.debug(f"[NOSIGNAL CHECK] Check {i + 1}")
                                    try:
                                        self.logo_compare.fail_if_logo_present_bytes(
                                            screenshot_bytes, str(nosignal_logo_path),
                                            x=840, y=810, width=260, height=140
                                        )
                                    except AssertionError:
                                        with open(check_ss_path, "wb") as f:
                                            f.write(screenshot_bytes)
                                        status = "FAILED"
                                        failed_step = "NoSignal Logo Detection"
                                        error_type = "NoSignalDetected"
                                        error_message = f"NoSignal detected at check {i + 1} for {app_name} on {self.device_id}"
                                        full_traceback = traceback.format_exc()
                                        log.error(f"[NOSIGNAL] ❌ {error_message}")
                                        raise

                                # ── Home logo check ──────────────────────────────────
                                home_logo_path = LOGO_DIR / "Home.png"
                                if home_logo_path.exists():
                                    log.debug(f"[HOME CHECK] Check {i + 1}")
                                    try:
                                        self.logo_compare.fail_if_logo_present_bytes(
                                            screenshot_bytes, str(home_logo_path),
                                            x=90, y=120, width=260, height=180
                                        )
                                    except AssertionError:
                                        with open(check_ss_path, "wb") as f:
                                            f.write(screenshot_bytes)
                                        status = "FAILED"
                                        failed_step = "Home Screen Detection"
                                        error_type = "HomeScreenDetected"
                                        error_message = f"Home screen detected at check {i + 1} for {app_name} on {self.device_id}"
                                        full_traceback = traceback.format_exc()
                                        log.error(f"[HOME] ❌ {error_message}")
                                        raise HomeScreenFailure(error_message)

                                # ── SNS logo check ───────────────────────────────────
                                sns_logo_path = LOGO_DIR / "SNS.png"
                                if sns_logo_path.exists():
                                    log.debug(f"[SNS CHECK] Check {i + 1}")
                                    try:
                                        self.logo_compare.fail_if_logo_present_bytes(
                                            screenshot_bytes, str(sns_logo_path),
                                            x=0, y=880, width=1920, height=200
                                        )
                                    except AssertionError:
                                        with open(check_ss_path, "wb") as f:
                                            f.write(screenshot_bytes)
                                        status = "FAILED"
                                        failed_step = "SNS Screen Detection"
                                        error_type = "SNS/Live ScreenDetected"
                                        error_message = f"SNS/Live screen detected at check {i + 1} for {app_name} on {self.device_id}"
                                        full_traceback = traceback.format_exc()
                                        log.error(f"[SNS] ❌ {error_message}")
                                        raise

                            # ── Wait out remaining playback time ─────────────────────
                            remaining = playback_end - time.time()
                            if remaining > 0:
                                log.debug(f"[WAIT] Final sleep {remaining:.2f}s")
                                time.sleep(remaining)

                            # ── Evaluate black screen failures ───────────────────────
                            if black_screen_failures:
                                status = "FAILED"
                                failed_step = "Black Screen Detection"
                                error_type = "BlackScreenError"
                                error_message = (
                                        f"{len(black_screen_failures)} black-screen check(s) failed: "
                                        + "; ".join(f"check {f['check_number']}: {f['error']}" for f in black_screen_failures)
                                )
                                full_traceback = error_message
                                log.error(f"[BLACK_SCREEN] {len(black_screen_failures)} failure(s) for content {content_num}")
                                raise BlackScreenFailure(error_message)
                            else:
                                log.info(f"[BLACK_SCREEN] All {num_checks} checks passed ✓")
                                log.info(f"✅ {app_name} — {content_name} PASSED on {self.device_id}")

                        except BlackScreenFailure as e:
                            log.error(f"[CONTENT {content_num}] Black screen failure — pressing home, will restart cycle from content 1")
                            try:
                                self.device.home()
                                time.sleep(2)
                            except Exception as home_exc:
                                log.warning(f"[BLACK_SCREEN] home() failed: {home_exc}")
                            already_at_home = True

                        except HomeScreenFailure as e:
                            log.error(f"[CONTENT {content_num}] Home screen detected — app crashed, will restart cycle from content 1")
                            already_at_home = True

                        except AssertionError as e:
                            status = "FAILED"
                            if not error_type:    error_type = "AssertionError"
                            if not error_message: error_message = str(e)
                            if not failed_step:   failed_step = "Content Validation"
                            if not full_traceback: full_traceback = traceback.format_exc()
                            log.error(f"[CONTENT {content_num}] Assertion failed: {e}", exc_info=True)
                            try:
                                ss = screenshots_folder / f"FAIL_c{content_num}_{app_name}_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                                self.device.take_screenshot(str(ss))
                            except Exception:
                                pass
                            # Navigate back to content selection screen
                            self.device.back()
                            time.sleep(1)
                            self.device.back()
                            time.sleep(1)

                        except Exception as e:
                            status = "FAILED"
                            error_type = type(e).__name__
                            error_message = str(e)
                            full_traceback = traceback.format_exc()
                            failed_step = "General Execution"
                            log.error(f"[CONTENT {content_num}] Unexpected error: {e}", exc_info=True)
                            try:
                                ss = screenshots_folder / f"ERROR_c{content_num}_{app_name}_{error_type}_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                                self.device.take_screenshot(str(ss))
                            except Exception:
                                pass
                            # Navigate back to content selection screen
                            self.device.back()
                            time.sleep(1)
                            self.device.back()
                            time.sleep(1)

                        finally:
                            # ── Always save result to Excel/CSV immediately (every attempt) ──
                            content_results.append(status == "PASSED")
                            log.info(
                                f"[REPORT] Content {content_num}/{num_contents} — app={app_name}, "
                                f"content={content_name}, status={status}, device={self.device_id}"
                            )
                            self.report_gen.add_result(
                                app_name=app_name,
                                content_name=content_name,
                                playback_time=test_case.get("playback_duration", SETTINGS.get("playback_duration", 30)),
                                device_id=self.device_id,
                                status=status,
                                screenshots_folder=str(screenshots_folder),
                                error_type=error_type,
                                error_message=error_message,
                                failed_step=failed_step,
                                full_traceback=full_traceback,
                            )
                            if status == "FAILED":
                                log.error(f"CONTENT {content_num} FAILED — {app_name} [{status}] - {error_type}: {error_message}")
                            else:
                                log.info(f"CONTENT {content_num} PASSED — {app_name} [{status}]")
                            if not _should_retry and status == "PASSED" and content_num < num_contents:
                                # ── Navigate back to content listing before next content ──
                                log.info(f"[NAV] Going back for content {content_num + 1}")
                                self.device.back()
                                time.sleep(1)
                                self.device.back()
                                time.sleep(1)

                        # ── Continue retry loop or exit ───────────────────────────
                        if _should_retry:
                            continue  # retry this content — re-launch from home on next iteration
                        break  # success or non-retryable failure — move to next content

                    # ── After all per-content retries: did this content ultimately pass? ──
                    if status == "FAILED":
                        cycle_at_home = already_at_home
                        cycle_content_failed = True
                        log.warning(
                            f"[CYCLE] Content {content_num}/{num_contents} failed after all retries "
                            f"— restarting from content 1 (cycle {cycle_attempt}/{max_cycle_retries})"
                        )
                        break  # Break content loop → cycle wrapper will restart from content 1

                # ── Evaluate cycle result ────────────────────────────────────
                if not cycle_content_failed:
                    log.info(f"[CYCLE {cycle_attempt}] All {num_contents} contents passed ✓")
                    break  # All contents passed — exit cycle loop
                elif cycle_attempt < max_cycle_retries:
                    log.warning(f"[CYCLE {cycle_attempt}/{max_cycle_retries}] Failed — restarting from content 1")
                else:
                    log.error(f"[CYCLE] All {max_cycle_retries} cycles exhausted for {app_name}")

            # ── After all contents: check if retry needed ────────────────
            if any(content_results):
                # At least one content passed - success, exit retry loop
                log.info(f"[APP RESULT] {app_name}: {sum(content_results)}/{num_contents} contents passed - SUCCESS")
                break  # Exit app retry loop
            else:
                # ALL contents failed
                if app_attempt < max_app_retries:
                    log.warning(f"[APP RESULT] {app_name}: ALL {num_contents} contents FAILED (attempt {app_attempt}/{max_app_retries})")
                    log.info(f"[RETRY] Will retry entire app {app_name}")
                    # Loop will continue to next app_attempt
                else:
                    log.error(f"[APP RESULT] {app_name}: ALL {num_contents} contents FAILED after {max_app_retries} attempts")
                    # All attempts exhausted - loop will exit naturally

        log.info("=" * 60)