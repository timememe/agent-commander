"""Desktop notification helpers with graceful fallback."""

from __future__ import annotations

import os


def send_notification(title: str, message: str) -> bool:
    """Send a desktop notification if a backend is available."""
    if os.name == "nt":
        try:
            from win10toast import ToastNotifier  # type: ignore[import-not-found]

            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=6, threaded=True)
            return True
        except Exception:
            pass

    try:
        from plyer import notification  # type: ignore[import-not-found]

        notification.notify(title=title, message=message, app_name="agent-commander-gui", timeout=6)
        return True
    except Exception:
        return False
