import logging
import time
from pathlib import Path


def navigate_back_until_home(
    device,
    logo_compare,
    home_logo_path,
    home_region=None,
    home_threshold=0.60,
    max_back_presses=8,
    max_home_presses=4,
    settle_seconds=1.0,
    logger=None,
):
    """Best-effort navigation to home by pressing BACK repeatedly, then HOME."""
    log = logger or logging.getLogger(__name__)
    region = home_region or [90, 120, 260, 180]
    logo_path = str(Path(home_logo_path))

    def _is_home_visible():
        try:
            screenshot_bytes = device.take_screenshot_bytes()
            logo_compare.fail_if_logo_not_present_bytes(
                screenshot_bytes,
                logo_path,
                x=region[0],
                y=region[1],
                width=region[2],
                height=region[3],
                threshold=home_threshold,
            )
            return True
        except Exception:
            return False

    if _is_home_visible():
        return True

    for attempt in range(1, max_back_presses + 1):
        try:
            device.back()
        except Exception as e:
            log.warning(f"[CLEANUP] BACK attempt {attempt} failed: {e}")
        time.sleep(settle_seconds)
        if _is_home_visible():
            log.info(f"[CLEANUP] Home detected after {attempt} BACK press(es)")
            return True

    for attempt in range(1, max_home_presses + 1):
        try:
            device.home()
        except Exception as e:
            log.warning(f"[CLEANUP] HOME attempt {attempt} failed: {e}")
        time.sleep(max(settle_seconds, 1.5))
        if _is_home_visible():
            log.info(f"[CLEANUP] Home detected after {attempt} HOME press(es)")
            return True

    log.warning(
        f"[CLEANUP] Home not detected after {max_back_presses} BACK and {max_home_presses} HOME attempt(s)"
    )
    return False
