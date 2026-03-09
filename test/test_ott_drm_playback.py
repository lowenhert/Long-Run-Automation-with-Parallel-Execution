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
from datetime import datetime


class BlackScreenFailure(Exception):
    """Raised when black-screen checks fail — NOT caught by the AssertionError handler
    so the finally block still runs, the result is recorded, and pytest moves on
    to the next parametrized app automatically."""
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
    """Load test cases from config - DRM ONLY"""
    selected_cases_file = os.getenv('SELECTED_CASES_FILE')
    if selected_cases_file and Path(selected_cases_file).exists():
        log.debug(f"Loading test cases from SELECTED_CASES_FILE: {selected_cases_file}")
        with open(selected_cases_file) as f:
            all_cases = yaml.safe_load(f)["test_cases"]
            return [case for case in all_cases if case.get("drm", False)]

    current_test_index = os.getenv('CURRENT_TEST_CASE')
    if current_test_index is not None:
        log.debug(f"Loading single test case at index {current_test_index}")
        with open("config/test_cases.yaml") as f:
            all_cases = yaml.safe_load(f)["test_cases"]
        try:
            index = int(current_test_index)
            if 0 <= index < len(all_cases):
                case = all_cases[index]
                if case.get("drm", False):
                    return [case]
                else:
                    log.warning(
                        f"CURRENT_TEST_CASE={index} is '{case['app_name']}' (drm=false). "
                        f"This file only handles DRM apps. Returning empty."
                    )
                    return []
        except (ValueError, IndexError):
            log.warning(f"Invalid CURRENT_TEST_CASE index: {current_test_index}, falling back to DRM cases")

    log.debug("Loading DRM test cases from config/test_cases.yaml")
    with open("config/test_cases.yaml") as f:
        all_cases = yaml.safe_load(f)["test_cases"]
        return [case for case in all_cases if case.get("drm", False)]


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

def parse_timestamp(text: str) -> int:
    """Convert HH:MM:SS or MM:SS string to total seconds. Returns -1 if not found."""
    # Match both HH:MM:SS and MM:SS formats
    match = re.search(r'(\d+):(\d{2}):(\d{2})', text)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return h * 3600 + m * 60 + s
    match = re.search(r'(\d+):(\d{2})', text)
    if match:
        m, s = int(match.group(1)), int(match.group(2))
        return m * 60 + s
    return -1


def verify_playback_progressing(ocr_lib, screenshot_bytes, previous_seconds, app_name, check_num,
                                region=(130, 695, 120, 35)) -> int:
    """
    OCR the timestamp region, parse it, and assert it is greater than previous.
    Returns the new timestamp in seconds.
    Raises AssertionError if time has not progressed.
    """
    x, y, w, h = region
    raw_text = ocr_lib.extract_text_from_region_bytes(screenshot_bytes, x, y, w, h).strip()
    log.debug(f"[TIMESTAMP] Check {check_num} raw OCR: '{raw_text}'")

    current_seconds = parse_timestamp(raw_text)

    if current_seconds == -1:
        log.warning(f"[TIMESTAMP] Check {check_num} — could not parse timestamp from '{raw_text}', skipping comparison")
        return previous_seconds  # don't fail, just skip this check

    log.info(f"[TIMESTAMP] Check {check_num} — previous={previous_seconds}s, current={current_seconds}s")

    if previous_seconds != -1 and current_seconds <= previous_seconds:
        msg = (
            f"Playback stalled for {app_name} at check {check_num}: "
            f"timestamp did not increase ({previous_seconds}s → {current_seconds}s)"
        )
        log.error(f"[TIMESTAMP] ❌ {msg}")
        raise AssertionError(msg)

    log.info(f"[TIMESTAMP] ✓ Playback progressing ({previous_seconds}s → {current_seconds}s)")
    return current_seconds


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
        """Main test – fully configurable per device with screenshots at each black-screen check"""
        app_name = test_case["app_name"]
        screenshots_folder = request.node.screenshot_dir

        log.info("=" * 60)
        log.info(f"TEST START — app={app_name}  device={self.device_id}")
        log.debug(f"Full test_case config: {test_case}")

        try:
            log.info("[HOME CHECK] Waiting for home screen before navigating…")
            home_logo_path = LOGO_DIR / "Home.png"
            max_home_attempts = 4
            home_detected = False
            for attempt in range(1, max_home_attempts + 1):
                screenshot_bytes = self.device.take_screenshot_bytes()
                try:
                    self.logo_compare.fail_if_logo_not_present_bytes(
                        screenshot_bytes, str(home_logo_path),
                        x=90, y=120, width=260, height=180,
                        threshold=0.60,
                    )
                    log.info(f"[HOME CHECK] ✓ Home screen detected on attempt {attempt}")
                    home_detected = True
                    break
                except AssertionError:
                    log.warning(
                        f"[HOME CHECK] Home not detected (attempt {attempt}/{max_home_attempts}), pressing HOME…")
                    self.device.home()
                    time.sleep(2)

            down = test_case["navigation"]["down_presses"]
            right = test_case["navigation"]["right_presses"]
            log.info(f"[NAVIGATION] Pressing DOWN x{down}, RIGHT x{right}")
            self.device.navigate_down(down)
            self.device.navigate_right(right)
            self.device.select()

            log.info("[NAVIGATION] Waiting 8 s for app to load…")
            time.sleep(8)

            screenshot_bytes = self.device.take_screenshot_bytes()
            verify_app_launch(test_case=test_case, ocr_lib=self.ocr, logo_lib=self.logo_compare,
                              screenshot_bytes=screenshot_bytes, region=(80, 100, 500, 200))
            log.info(f"[APP LAUNCH] ✓ {app_name} launched successfully")

        except Exception as launch_exc:
            # App didn't launch — log one FAILED row and bail out
            log.error(f"[APP LAUNCH] ❌ Failed to launch {app_name}: {launch_exc}", exc_info=True)
            try:
                failure_ss_path = (
                        screenshots_folder
                        / f"LAUNCH_FAIL_{app_name}_{int(time.time())}_{self.device_id.replace(':', '_')}.png"
                )
                self.device.take_screenshot(str(failure_ss_path))
            except Exception:
                pass

            self.report_gen.add_result(app_name=app_name, content_name="App Launch Failed", playback_time=0,
                                       device_id=self.device_id,
                                       status="FAILED",
                                       screenshots_folder=str(screenshots_folder),
                                       error_type=type(launch_exc).__name__,
                                       error_message=str(launch_exc),
                                       failed_step="App Launch",
                                       full_traceback=traceback.format_exc(),
                                       )
            log.error(f"TEST FAILED — {app_name} could not launch")
            log.info("=" * 60)
            raise

        num_contents = test_case.get("random_content_plays", 2)

        for content_num in range(1, num_contents + 1):
            # Per-content result variables — reset each iteration
            content_name = test_case.get("content_name_fallback", app_name)
            status = "PASSED"
            error_type = ""
            error_message = ""
            failed_step = ""
            full_traceback = ""

            log.info("-" * 60)
            log.info(f"[CONTENT {content_num}/{num_contents}] Starting random content selection")

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
                    resume = self.ocr.extract_text_from_region_bytes(screenshot_bytes, rx, ry, rw, rh).strip()
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

                time.sleep(15)     #sleep duration increased as DRM apps take longer to load
                playback_duration = test_case.get("playback_duration", SETTINGS.get("playback_duration", 30))
                log.info(f"[PLAYBACK] Monitoring for {playback_duration} seconds")

                check_interval = SETTINGS["check_interval"]

                playback_start = time.time()
                playback_end = playback_start + playback_duration
                num_checks = max(1, playback_duration // check_interval)
                previous_timestamp_seconds = -1
                timestamp_parse_failures = 0
                ts_region = (172, 917, 94, 38)

                for i in range(num_checks):
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

                    self.device.navigate_down(1)
                    Pause_logo_path = LOGO_DIR / "pause.png"
                    screenshot_bytes = self.device.take_screenshot_bytes()
                    self.logo_compare.fail_if_logo_not_present_bytes(screenshot_bytes, str(Pause_logo_path),x=60,y=888,width=96,height=96)
                    log.info(f"Content is playing , pause button detected")

                    self.device.navigate_down(1)
                    screenshot_bytes = self.device.take_screenshot_bytes()

                    try:

                        x, y, w, h = ts_region
                        raw_text = self.ocr.extract_text_from_region_bytes(
                            screenshot_bytes, x, y, w, h
                        ).strip()
                        log.debug(f"[TIMESTAMP] Check {i + 1} raw OCR: '{raw_text}'")

                        current_seconds = parse_timestamp(raw_text)

                        if current_seconds == -1:
                            timestamp_parse_failures += 1
                            log.warning(f"[TIMESTAMP] Check {i + 1} — could not parse '{raw_text}', skipping")
                            continue  # skip this check but count it

                        if previous_timestamp_seconds != -1 and current_seconds <= previous_timestamp_seconds:
                            raise AssertionError(
                                f"Playback stalled: {previous_timestamp_seconds}s → {current_seconds}s")

                        previous_timestamp_seconds = current_seconds

                    except AssertionError as ts_exc:
                        with open(check_ss_path, "wb") as f:
                            f.write(screenshot_bytes)
                        status = "FAILED"
                        failed_step = "Playback Progression"
                        error_type = "PlaybackStalled"
                        error_message = str(ts_exc)
                        full_traceback = traceback.format_exc()
                        log.error(f"[TIMESTAMP] ❌ {error_message}")
                        raise


                    # ── TataPlay logo check ──────────────────────────────
                    TP_logo_path = LOGO_DIR / "TP_logo.png"
                    if TP_logo_path.exists():
                        log.debug(f"[TataPlay logo CHECK] Check {i + 1}")
                        try:
                            self.logo_compare.fail_if_logo_present_bytes(
                                screenshot_bytes, str(TP_logo_path),
                                x=80, y=52, width=250, height=78           #[80,52][330,130]
                            )
                        except AssertionError:
                            with open(check_ss_path, "wb") as f:
                                f.write(screenshot_bytes)
                            status = "FAILED"
                            failed_step = "TataPlay Logo Detection"
                            error_type = "TataPlayDetected"
                            error_message = f"TataPlay logo detected at check {i + 1} for {app_name} on {self.device_id}, content not playing"
                            full_traceback = traceback.format_exc()
                            log.error(f"[TataPlay Logo] ❌ {error_message}")
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
                            raise

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

                # ── Fail if timestamp never parsed across all checks ──────
                if timestamp_parse_failures == num_checks:
                    raise AssertionError(
                        f"Timestamp OCR failed on all {num_checks} checks for {app_name} — "
                        f"region {ts_region} may be wrong"
                    )
                # ── Wait out remaining playback time ─────────────────────
                remaining = playback_end - time.time()
                if remaining > 0:
                    log.debug(f"[WAIT] Final sleep {remaining:.2f}s")
                    time.sleep(remaining)

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

            finally:
                # ── Log this content's result to CSV ─────────────────────
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

            # ── Go back to app home screen before next content ───────────
            if content_num < num_contents:
                log.info(f"[NAV] Going back for content {content_num + 1}")
                self.device.back()
                time.sleep(1)
                self.device.back()
                time.sleep(1)

        log.info("=" * 60)