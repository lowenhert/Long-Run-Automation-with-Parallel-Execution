import logging

import cv2
import numpy as np
from robot.api.deco import keyword

log = logging.getLogger(__name__)


class LogoCompareLibrary:

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    # ── internal helpers ───────────────────────────────────────────────────

    def _get_driver(self):
        """
        Returns the Appium driver when running inside Robot Framework.
        Outside RF (e.g. pytest) this is never called — callers pass
        screenshot bytes directly via fail_if_logo_not_present_bytes().
        """
        try:
            from robot.libraries.BuiltIn import BuiltIn
            appium_lib = BuiltIn().get_library_instance("AppiumLibrary")
            return appium_lib._current_application()
        except Exception as e:
            raise RuntimeError(
                "Appium driver not available outside Robot Framework. "
                "Use fail_if_logo_not_present_bytes() and pass PNG bytes directly."
            ) from e

    @staticmethod
    def _match_logo(png_bytes: bytes,
                    reference_logo_path: str,
                    x: int, y: int,
                    width: int, height: int,
                    threshold: float) -> float:
        """Core CV logic shared by both the RF keyword and the pytest helper."""
        nparr = np.frombuffer(png_bytes, np.uint8)
        screen = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if screen is None:
            raise ValueError("[LOGO] Could not decode screenshot PNG bytes")

        region = screen[y:y + height, x:x + width]

        logo = cv2.imread(reference_logo_path, cv2.IMREAD_COLOR)
        if logo is None:
            raise AssertionError(f"[LOGO] Reference logo not found at: {reference_logo_path}")

        region_gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        logo_gray = cv2.cvtColor(logo, cv2.COLOR_BGR2GRAY)

        result = cv2.matchTemplate(region_gray, logo_gray, cv2.TM_CCOEFF_NORMED)
        _, score, _, _ = cv2.minMaxLoc(result)
        return float(score)

    # ── public API ─────────────────────────────────────────────────────────

    @keyword("Fail If Logo Not Present")
    def fail_if_logo_not_present(self, reference_logo_path,
                                 x, y, width, height,
                                 threshold=0.60):
        """
        Robot Framework entry point — grabs screenshot via Appium driver.
        """
        x, y, width, height = int(x), int(y), int(width), int(height)
        threshold = float(threshold)
        log.info(
            f"[LOGO] fail_if_logo_not_present — logo={reference_logo_path!r} "
            f"region=({x},{y},{width},{height}) threshold={threshold}"
        )

        driver = self._get_driver()
        png_bytes = driver.get_screenshot_as_png()
        self.fail_if_logo_not_present_bytes(png_bytes, reference_logo_path,
                                            x, y, width, height, threshold)

    def fail_if_logo_not_present_bytes(self, png_bytes: bytes,
                                       reference_logo_path: str,
                                       x: int, y: int,
                                       width: int, height: int,
                                       threshold: float = 0.80):
        """
        Pytest-friendly entry point.
        Pass raw PNG bytes (e.g. from DeviceController.take_screenshot_bytes()).
        Raises AssertionError if the logo confidence is below threshold.
        """
        x, y, width, height = int(x), int(y), int(width), int(height)
        threshold = float(threshold)
        log.info(
            f"[LOGO] fail_if_logo_not_present_bytes — logo={reference_logo_path!r} "
            f"region=({x},{y},{width},{height}) threshold={threshold}"
        )

        score = self._match_logo(png_bytes, reference_logo_path,
                                 x, y, width, height, threshold)

        log.debug(f"[LOGO] Match score: {score:.4f} (threshold={threshold})")

        if score < threshold:
            msg = (
                f"App logo NOT detected. "
                f"Confidence={score:.2f}, Threshold={threshold}, "
                f"Logo={reference_logo_path}"
            )
            log.error(f"[LOGO] ❌ {msg}")
            raise AssertionError(msg)

        log.info(f"[LOGO] ✓ Logo detected. Confidence={score:.2f}")
    
    def fail_if_logo_present_bytes(self, png_bytes, reference_logo_path,
                               x, y, width, height,
                               threshold=0.60):
     score = self._match_logo(png_bytes, reference_logo_path,
                             x, y, width, height, threshold)

     log.info(f"[DEBUG] Match score: {score:.4f}, threshold={threshold}")
     if score >= threshold:
        raise AssertionError(
            f"Logo detected (unexpected). Confidence={score:.2f}"
        )