"""
appium_utils.py
---------------
Reusable Appium helper library for Android TV / Android device automation.

Complements the existing ADB-based DeviceController — use this when you need
UI-level element interaction (find, click, type, scroll, etc.) via Appium,
while DeviceController handles low-level ADB key events and screenshots.

Typical usage in a test:
    from libraries.appium_utils import AppiumDriver, AppiumHelper

    # 1. Build a driver for one device
    driver = AppiumDriver.create(device_id="172.18.1.114:5555", app_package="com.example.app")

    # 2. Wrap it with the helper
    ui = AppiumHelper(driver)

    # 3. Use helper functions
    ui.click_by_id("com.example.app:id/play_button")
    text = ui.get_text_by_id("com.example.app:id/title_label")
    ui.wait_for_element_by_id("com.example.app:id/loading_spinner", timeout=10)

    # 4. Quit when done
    driver.quit()
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Default Appium server URL — override via AppiumDriver.create(appium_url=...)
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_APPIUM_URL = "http://localhost:4723"


# =============================================================================
# AppiumDriver  —  thin wrapper around webdriver.Remote for easy session setup
# =============================================================================

class AppiumDriver:
    """
    Factory helper that builds an Appium WebDriver session for an Android device.

    Parameters
    ----------
    device_id : str
        ADB device serial or IP:port (e.g. "172.18.1.114:5555").
    app_package : str
        Android app package name (e.g. "com.example.ottapp").
    app_activity : str, optional
        Main activity to launch.  If omitted, Appium uses the default launcher.
    appium_url : str, optional
        Appium server URL.  Defaults to ``http://localhost:4723``.
    platform_version : str, optional
        Android OS version string (e.g. "12").
    extra_caps : dict, optional
        Any additional desired capabilities to merge in.
    """

    # ------------------------------------------------------------------ #
    #  Factory                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def create(
        device_id: str,
        app_package: str = "",
        app_activity: str = "",
        appium_url: str = DEFAULT_APPIUM_URL,
        platform_version: str = "",
        extra_caps: Optional[dict] = None,
    ) -> webdriver.Remote:
        """
        Create and return an Appium ``webdriver.Remote`` instance.

        Example
        -------
        >>> driver = AppiumDriver.create(
        ...     device_id="172.18.1.114:5555",
        ...     app_package="com.example.app",
        ...     app_activity=".MainActivity",
        ... )
        """
        options = AppiumOptions()
        options.platform_name = "Android"
        options.set_capability("deviceName", device_id)
        options.set_capability("udid", device_id)
        options.set_capability("automationName", "UiAutomator2")
        options.set_capability("noReset", True)       # keep app state between runs
        options.set_capability("newCommandTimeout", 180)

        if platform_version:
            options.set_capability("platformVersion", platform_version)
        if app_package:
            options.set_capability("appPackage", app_package)
        if app_activity:
            options.set_capability("appActivity", app_activity)

        # Merge caller-supplied extras
        if extra_caps:
            for key, value in extra_caps.items():
                options.set_capability(key, value)

        log.info(f"[AppiumDriver] Connecting to {appium_url} | device={device_id} | pkg={app_package}")
        driver = webdriver.Remote(appium_url, options=options)
        log.info("[AppiumDriver] Session created — id=%s", driver.session_id)
        return driver

    # ------------------------------------------------------------------ #
    #  Convenience: launch/stop an existing driver session                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def launch_app(driver: webdriver.Remote, app_package: str, app_activity: str = "") -> None:
        """Activate (bring to foreground) a specific app without re-installing."""
        driver.activate_app(app_package)
        log.info(f"[AppiumDriver] App activated: {app_package}")

    @staticmethod
    def close_app(driver: webdriver.Remote, app_package: str) -> None:
        """Terminate (kill) a running app."""
        driver.terminate_app(app_package)
        log.info(f"[AppiumDriver] App terminated: {app_package}")

    @staticmethod
    def quit(driver: webdriver.Remote) -> None:
        """Quit the Appium session cleanly."""
        try:
            driver.quit()
            log.info("[AppiumDriver] Session closed")
        except Exception as exc:
            log.warning(f"[AppiumDriver] Error closing session: {exc}")


# =============================================================================
# AppiumHelper  —  all reusable UI interaction functions
# =============================================================================

class AppiumHelper:
    """
    Wraps an Appium ``webdriver.Remote`` and exposes high-level helpers.

    All ``find_*`` / ``click_*`` / ``wait_*`` methods accept an optional
    ``timeout`` parameter (default: 10 s).  Methods that cannot find an element
    raise ``NoSuchElementException`` unless documented otherwise.

    Parameters
    ----------
    driver : webdriver.Remote
        Active Appium driver session (created by :class:`AppiumDriver`).
    default_timeout : int
        Default wait timeout in seconds used when no explicit timeout is given.
    """

    def __init__(self, driver: webdriver.Remote, default_timeout: int = 15):
        self.driver = driver
        self.default_timeout = default_timeout

    # ================================================================== #
    #  FIND ELEMENT(S)                                                    #
    # ================================================================== #

    def find_by_id(self, resource_id: str, timeout: Optional[int] = None) -> WebElement:
        """
        Return the first element matching the given resource ID.

        Parameters
        ----------
        resource_id : str
            Full resource ID, e.g. ``"com.example.app:id/play_button"``.

        Raises
        ------
        NoSuchElementException
            If no element is found within *timeout* seconds.
        """
        return self._wait_for(AppiumBy.ID, resource_id, timeout)

    def find_all_by_id(self, resource_id: str, timeout: Optional[int] = None) -> List[WebElement]:
        """Return *all* elements matching the given resource ID."""
        return self._wait_for_all(AppiumBy.ID, resource_id, timeout)

    def find_by_xpath(self, xpath: str, timeout: Optional[int] = None) -> WebElement:
        """Return the first element matching *xpath*."""
        return self._wait_for(AppiumBy.XPATH, xpath, timeout)

    def find_all_by_xpath(self, xpath: str, timeout: Optional[int] = None) -> List[WebElement]:
        """Return all elements matching *xpath*."""
        return self._wait_for_all(AppiumBy.XPATH, xpath, timeout)

    def find_by_text(self, text: str, timeout: Optional[int] = None) -> WebElement:
        """Return the first element whose visible text *exactly* matches *text*."""
        xpath = f'//*[@text="{text}"]'
        return self._wait_for(AppiumBy.XPATH, xpath, timeout)

    def find_by_text_contains(self, partial_text: str, timeout: Optional[int] = None) -> WebElement:
        """Return the first element whose visible text *contains* *partial_text*."""
        xpath = f'//*[contains(@text, "{partial_text}")]'
        return self._wait_for(AppiumBy.XPATH, xpath, timeout)

    def find_by_class(self, class_name: str, timeout: Optional[int] = None) -> WebElement:
        """Return the first element of the given UI class, e.g. ``android.widget.Button``."""
        return self._wait_for(AppiumBy.CLASS_NAME, class_name, timeout)

    def find_all_by_class(self, class_name: str, timeout: Optional[int] = None) -> List[WebElement]:
        """Return all elements of a given UI class."""
        return self._wait_for_all(AppiumBy.CLASS_NAME, class_name, timeout)

    def find_by_content_desc(self, description: str, timeout: Optional[int] = None) -> WebElement:
        """Return element by content-desc / accessibility label."""
        return self._wait_for(AppiumBy.ACCESSIBILITY_ID, description, timeout)

    def find_by_uiautomator(self, uia_selector: str, timeout: Optional[int] = None) -> WebElement:
        """
        Return element via UiAutomator2 selector string.

        Example
        -------
        >>> el = ui.find_by_uiautomator('new UiSelector().text("Play")')
        """
        return self._wait_for(AppiumBy.ANDROID_UIAUTOMATOR, uia_selector, timeout)

    # ================================================================== #
    #  ELEMENT EXISTS CHECK                                               #
    # ================================================================== #

    def exists_by_id(self, resource_id: str, timeout: int = 3) -> bool:
        """Return ``True`` if element with *resource_id* is present within *timeout* s."""
        return self._exists(AppiumBy.ID, resource_id, timeout)

    def exists_by_xpath(self, xpath: str, timeout: int = 3) -> bool:
        """Return ``True`` if an element matching *xpath* is present within *timeout* s."""
        return self._exists(AppiumBy.XPATH, xpath, timeout)

    def exists_by_text(self, text: str, timeout: int = 3) -> bool:
        """Return ``True`` if an element with the exact *text* is visible."""
        return self._exists(AppiumBy.XPATH, f'//*[@text="{text}"]', timeout)

    def exists_by_content_desc(self, description: str, timeout: int = 3) -> bool:
        """Return ``True`` if an element with *description* accessibility label exists."""
        return self._exists(AppiumBy.ACCESSIBILITY_ID, description, timeout)

    # ================================================================== #
    #  CLICK                                                              #
    # ================================================================== #

    def click_by_id(self, resource_id: str, timeout: Optional[int] = None) -> None:
        """Find element by ID and click it."""
        el = self.find_by_id(resource_id, timeout)
        el.click()
        log.debug(f"[click_by_id] Clicked: {resource_id}")

    def click_by_xpath(self, xpath: str, timeout: Optional[int] = None) -> None:
        """Find element by XPath and click it."""
        el = self.find_by_xpath(xpath, timeout)
        el.click()
        log.debug(f"[click_by_xpath] Clicked: {xpath}")

    def click_by_text(self, text: str, timeout: Optional[int] = None) -> None:
        """Find element by exact text and click it."""
        el = self.find_by_text(text, timeout)
        el.click()
        log.debug(f"[click_by_text] Clicked text: {text}")

    def click_by_text_contains(self, partial_text: str, timeout: Optional[int] = None) -> None:
        """Find element by partial text and click it."""
        el = self.find_by_text_contains(partial_text, timeout)
        el.click()
        log.debug(f"[click_by_text_contains] Clicked partial text: {partial_text}")

    def click_by_content_desc(self, description: str, timeout: Optional[int] = None) -> None:
        """Find element by content-desc and click it."""
        el = self.find_by_content_desc(description, timeout)
        el.click()
        log.debug(f"[click_by_content_desc] Clicked: {description}")

    def click_coordinates(self, x: int, y: int) -> None:
        """Tap at absolute screen coordinates (*x*, *y*)."""
        self.driver.tap([(x, y)])
        log.debug(f"[click_coordinates] Tapped ({x}, {y})")

    # ================================================================== #
    #  TEXT INPUT                                                         #
    # ================================================================== #

    def send_keys_by_id(self, resource_id: str, text: str, clear_first: bool = True,
                        timeout: Optional[int] = None) -> None:
        """
        Find an input field by ID and type *text* into it.

        Parameters
        ----------
        clear_first : bool
            If ``True`` (default) the field is cleared before typing.
        """
        el = self.find_by_id(resource_id, timeout)
        if clear_first:
            el.clear()
        el.send_keys(text)
        log.debug(f"[send_keys_by_id] Sent '{text}' to {resource_id}")

    def send_keys_by_xpath(self, xpath: str, text: str, clear_first: bool = True,
                           timeout: Optional[int] = None) -> None:
        """Find an input field by XPath and type *text* into it."""
        el = self.find_by_xpath(xpath, timeout)
        if clear_first:
            el.clear()
        el.send_keys(text)
        log.debug(f"[send_keys_by_xpath] Sent '{text}' to {xpath}")

    # ================================================================== #
    #  GET TEXT / ATTRIBUTE                                               #
    # ================================================================== #

    def get_text_by_id(self, resource_id: str, timeout: Optional[int] = None) -> str:
        """Return the visible text of the element with *resource_id*."""
        return self.find_by_id(resource_id, timeout).text

    def get_text_by_xpath(self, xpath: str, timeout: Optional[int] = None) -> str:
        """Return the visible text of the first element matching *xpath*."""
        return self.find_by_xpath(xpath, timeout).text

    def get_attribute_by_id(self, resource_id: str, attribute: str,
                            timeout: Optional[int] = None) -> str:
        """
        Return the value of *attribute* on the element with *resource_id*.

        Common attributes: ``"text"``, ``"enabled"``, ``"focused"``,
        ``"selected"``, ``"content-desc"``, ``"resource-id"``,
        ``"className"``, ``"bounds"``.
        """
        return self.find_by_id(resource_id, timeout).get_attribute(attribute)

    def get_attribute_by_xpath(self, xpath: str, attribute: str,
                               timeout: Optional[int] = None) -> str:
        """Return the value of *attribute* on the first element matching *xpath*."""
        return self.find_by_xpath(xpath, timeout).get_attribute(attribute)

    def is_element_focused(self, resource_id: str, timeout: Optional[int] = None) -> bool:
        """Return ``True`` if element with *resource_id* currently has focus."""
        return self.get_attribute_by_id(resource_id, "focused", timeout) == "true"

    def is_element_enabled(self, resource_id: str, timeout: Optional[int] = None) -> bool:
        """Return ``True`` if element with *resource_id* is enabled."""
        return self.get_attribute_by_id(resource_id, "enabled", timeout) == "true"

    def is_element_selected(self, resource_id: str, timeout: Optional[int] = None) -> bool:
        """Return ``True`` if element with *resource_id* is selected/checked."""
        return self.get_attribute_by_id(resource_id, "selected", timeout) == "true"

    # ================================================================== #
    #  WAIT HELPERS                                                       #
    # ================================================================== #

    def wait_for_element_by_id(self, resource_id: str, timeout: Optional[int] = None) -> WebElement:
        """Block until the element with *resource_id* is visible, then return it."""
        return self._wait_for(AppiumBy.ID, resource_id, timeout)

    def wait_for_element_by_xpath(self, xpath: str, timeout: Optional[int] = None) -> WebElement:
        """Block until the first element matching *xpath* is visible, then return it."""
        return self._wait_for(AppiumBy.XPATH, xpath, timeout)

    def wait_for_element_by_text(self, text: str, timeout: Optional[int] = None) -> WebElement:
        """Block until an element with exactly *text* is visible."""
        return self._wait_for(AppiumBy.XPATH, f'//*[@text="{text}"]', timeout)

    def wait_until_gone_by_id(self, resource_id: str, timeout: Optional[int] = None) -> bool:
        """
        Block until the element with *resource_id* disappears from the screen.

        Returns
        -------
        bool
            ``True`` if it disappeared within *timeout*, ``False`` otherwise.
        """
        t = timeout if timeout is not None else self.default_timeout
        try:
            WebDriverWait(self.driver, t).until_not(
                EC.presence_of_element_located((AppiumBy.ID, resource_id))
            )
            log.debug(f"[wait_until_gone_by_id] Element gone: {resource_id}")
            return True
        except TimeoutException:
            log.debug(f"[wait_until_gone_by_id] Element still present after {t}s: {resource_id}")
            return False

    def sleep(self, seconds: float) -> None:
        """Pause execution for *seconds*."""
        time.sleep(seconds)

    # ================================================================== #
    #  SCROLL / SWIPE                                                     #
    # ================================================================== #

    def scroll_down(self, swipe_duration_ms: int = 600) -> None:
        """Scroll the screen downward (swipe up gesture)."""
        self._vertical_swipe(direction="down", duration=swipe_duration_ms)
        log.debug("[scroll_down] Scrolled down")

    def scroll_up(self, swipe_duration_ms: int = 600) -> None:
        """Scroll the screen upward (swipe down gesture)."""
        self._vertical_swipe(direction="up", duration=swipe_duration_ms)
        log.debug("[scroll_up] Scrolled up")

    def scroll_to_text(self, text: str) -> WebElement:
        """
        Scroll until the element with the given *text* becomes visible.

        Uses the native UiScrollable UiAutomator selector.
        """
        selector = (
            f'new UiScrollable(new UiSelector().scrollable(true).instance(0))'
            f'.scrollIntoView(new UiSelector().text("{text}").instance(0))'
        )
        el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
        log.debug(f"[scroll_to_text] Scrolled to: {text}")
        return el

    def scroll_to_id(self, resource_id: str) -> WebElement:
        """Scroll until the element with *resource_id* is visible."""
        selector = (
            f'new UiScrollable(new UiSelector().scrollable(true).instance(0))'
            f'.scrollIntoView(new UiSelector().resourceId("{resource_id}").instance(0))'
        )
        el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
        log.debug(f"[scroll_to_id] Scrolled to ID: {resource_id}")
        return el

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int,
              duration_ms: int = 500) -> None:
        """Perform a raw swipe gesture from (start_x, start_y) to (end_x, end_y)."""
        self.driver.swipe(start_x, start_y, end_x, end_y, duration_ms)
        log.debug(f"[swipe] ({start_x},{start_y}) → ({end_x},{end_y})")

    # ================================================================== #
    #  NAVIGATION (complements DeviceController ADB keypresses)          #
    # ================================================================== #

    def press_back(self) -> None:
        """Press the Android back button via Appium."""
        self.driver.back()
        log.debug("[press_back] Back pressed")

    def press_home(self) -> None:
        """Press the Android home button via key event."""
        self.driver.press_keycode(3)   # KEYCODE_HOME
        log.debug("[press_home] Home pressed")

    def press_enter(self) -> None:
        """Press the DPAD center / enter key."""
        self.driver.press_keycode(23)  # KEYCODE_DPAD_CENTER
        log.debug("[press_enter] Enter pressed")

    def press_dpad_up(self) -> None:
        """Press DPAD up."""
        self.driver.press_keycode(19)

    def press_dpad_down(self) -> None:
        """Press DPAD down."""
        self.driver.press_keycode(20)

    def press_dpad_left(self) -> None:
        """Press DPAD left."""
        self.driver.press_keycode(21)

    def press_dpad_right(self) -> None:
        """Press DPAD right."""
        self.driver.press_keycode(22)

    def press_keycode(self, keycode: int, metastate: int = 0) -> None:
        """Send any arbitrary Android keycode."""
        self.driver.press_keycode(keycode, metastate)
        log.debug(f"[press_keycode] keycode={keycode}")

    # ================================================================== #
    #  APP MANAGEMENT                                                     #
    # ================================================================== #

    def launch_app(self, app_package: str, app_activity: str = "") -> None:
        """Activate (bring to foreground) *app_package*."""
        self.driver.activate_app(app_package)
        log.info(f"[launch_app] Launched: {app_package}")

    def close_app(self, app_package: str) -> None:
        """Terminate (kill) *app_package*."""
        self.driver.terminate_app(app_package)
        log.info(f"[close_app] Closed: {app_package}")

    def get_current_activity(self) -> str:
        """Return the currently focused activity name."""
        return self.driver.current_activity

    def get_current_package(self) -> str:
        """Return the currently focused package name."""
        return self.driver.current_package

    def is_app_running(self, app_package: str) -> bool:
        """
        Return ``True`` if *app_package* is currently in the foreground.
        """
        return self.get_current_package() == app_package

    # ================================================================== #
    #  SCREENSHOT                                                         #
    # ================================================================== #

    def get_screenshot_as_png(self) -> bytes:
        """Return the current screen as raw PNG bytes (no disk I/O)."""
        return self.driver.get_screenshot_as_png()

    def save_screenshot(self, path: str) -> str:
        """
        Save the current screen to *path* and return the path.

        Parameters
        ----------
        path : str
            Destination file path, e.g. ``"screenshots/home.png"``
        """
        self.driver.save_screenshot(path)
        log.info(f"[save_screenshot] Saved to: {path}")
        return path

    # ================================================================== #
    #  INTERNAL HELPERS                                                   #
    # ================================================================== #

    def _wait_for(self, by: str, value: str, timeout: Optional[int]) -> WebElement:
        """Wait until element is present and return it."""
        t = timeout if timeout is not None else self.default_timeout
        try:
            return WebDriverWait(self.driver, t).until(
                EC.presence_of_element_located((by, value))
            )
        except TimeoutException:
            raise NoSuchElementException(
                f"Element not found — by={by!r}  value={value!r}  timeout={t}s"
            )

    def _wait_for_all(self, by: str, value: str, timeout: Optional[int]) -> List[WebElement]:
        """Wait until at least one element is present and return all matches."""
        t = timeout if timeout is not None else self.default_timeout
        try:
            WebDriverWait(self.driver, t).until(
                EC.presence_of_element_located((by, value))
            )
            return self.driver.find_elements(by, value)
        except TimeoutException:
            return []

    def _exists(self, by: str, value: str, timeout: int) -> bool:
        """Return True if element appears within *timeout* seconds."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return True
        except (TimeoutException, NoSuchElementException, WebDriverException):
            return False

    def _vertical_swipe(self, direction: str = "down", duration: int = 600) -> None:
        """Helper for scroll_up / scroll_down."""
        size = self.driver.get_window_size()
        w, h = size["width"], size["height"]
        mid_x = w // 2
        if direction == "down":
            start_y, end_y = int(h * 0.75), int(h * 0.25)
        else:
            start_y, end_y = int(h * 0.25), int(h * 0.75)
        self.driver.swipe(mid_x, start_y, mid_x, end_y, duration)
