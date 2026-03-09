import logging

import cv2
import numpy as np
import pytesseract
from robot.api.deco import keyword

log = logging.getLogger(__name__)


class OcrLibrary:

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, tesseract_cmd: str = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            log.debug(f"[OCR] Tesseract path set to: {tesseract_cmd}")

    # ── internal helpers ───────────────────────────────────────────────────

    def _get_driver(self):
        """
        Returns the Appium driver when running inside Robot Framework.
        Outside RF (e.g. pytest) this is never called — callers pass
        screenshot bytes directly via extract_text_from_region_bytes().
        """
        try:
            from robot.libraries.BuiltIn import BuiltIn
            appium_lib = BuiltIn().get_library_instance("AppiumLibrary")
            return appium_lib._current_application()
        except Exception as e:
            raise RuntimeError(
                "Appium driver not available outside Robot Framework. "
                "Use extract_text_from_region_bytes() instead and pass screenshot bytes directly."
            ) from e

    @staticmethod
    def _png_bytes_to_image(png_bytes: bytes):
        nparr = np.frombuffer(png_bytes, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    @staticmethod
    def _run_ocr(image) -> str:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, gray = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        return pytesseract.image_to_string(gray).strip()

    @staticmethod
    def _crop(image, x: int, y: int, width: int, height: int):
        img_h, img_w = image.shape[:2]
        if x < 0 or y < 0 or x + width > img_w or y + height > img_h:
            raise ValueError(
                f"Region out of bounds. Image: {img_w}x{img_h}, "
                f"Region: x={x} y={y} w={width} h={height}"
            )
        return image[y:y + height, x:x + width]

    # ── public API ─────────────────────────────────────────────────────────

    @keyword("Extract Text From Region")
    def extract_text_from_region(self, x, y, width, height) -> str:
        """
        Robot Framework entry point — grabs a screenshot via Appium driver
        and runs OCR on the specified region.
        """
        x, y, width, height = int(x), int(y), int(width), int(height)
        log.info(f"[OCR] extract_text_from_region(x={x}, y={y}, w={width}, h={height}) via Appium driver")

        driver = self._get_driver()
        png_bytes = driver.get_screenshot_as_png()
        return self.extract_text_from_region_bytes(png_bytes, x, y, width, height)

    def extract_text_from_region_bytes(self, png_bytes: bytes,
                                       x: int, y: int,
                                       width: int, height: int) -> str:
        """
        Pytest-friendly entry point.
        Pass raw PNG bytes (e.g. from DeviceController.take_screenshot_bytes())
        and get back the OCR text for the requested region.
        """
        x, y, width, height = int(x), int(y), int(width), int(height)
        log.info(f"[OCR] extract_text_from_region_bytes(x={x}, y={y}, w={width}, h={height})")

        image = self._png_bytes_to_image(png_bytes)
        if image is None:
            raise ValueError("[OCR] Could not decode PNG bytes into an image")

        cropped = self._crop(image, x, y, width, height)
        text = self._run_ocr(cropped)

        log.debug(f"[OCR] Extracted text: {text!r}")
        return text