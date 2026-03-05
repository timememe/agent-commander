"""Settings panel — CLIProxyAPI server status and provider OAuth login."""

from __future__ import annotations

import re
import threading
import time
import webbrowser
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme

if TYPE_CHECKING:
    pass

_PROVIDERS = [("claude", "Claude"), ("gemini", "Gemini"), ("codex", "Codex")]
_LOGIN_TIMEOUT_S = 180.0
_LOGIN_POLL_S = 0.5
_URL_RE = re.compile(r"https://\S+")

# Model ID prefixes used to filter server models per provider
_MODEL_PREFIXES: dict[str, tuple[str, ...]] = {
    "claude": ("claude",),
    "gemini": ("gemini",),
    "codex": ("gpt-", "codex", "o1-", "o3-", "o4-"),
}

_PROVIDER_LOGIN_HINTS = {
    "claude": "1) Open URL.  2) Complete browser auth.  3) Press Enter below if prompted.",
    "gemini": "1) Open URL.  2) Complete Google auth.  3) Enter mode number below if prompted.",
    "codex": "1) Open URL.  2) Complete OpenAI auth.  3) Press Enter below after callback.",
}


# ---------------------------------------------------------------------------
# Thread-safe signal relay
# ---------------------------------------------------------------------------

class _Relay(QObject):
    """Tiny QObject used only to carry cross-thread signals."""
    msg = Signal(str, object)   # (action, payload)


# ---------------------------------------------------------------------------
# Settings panel
# ---------------------------------------------------------------------------

class SettingsPanel(QWidget):
    """CLIProxyAPI server status + per-provider OAuth login."""

    def __init__(
        self,
        server_manager: object | None = None,
        on_model_change: Callable[[str, str], None] | None = None,
        model_defaults: dict[str, str] | None = None,
        on_restart_app: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._manager = server_manager
        self._on_model_change = on_model_change
        self._model_defaults: dict[str, str] = model_defaults or {}
        self._on_restart_app = on_restart_app

        self._status_labels: dict[str, QLabel] = {}
        self._auth_buttons: dict[str, QPushButton] = {}
        self._provider_connected: dict[str, bool] = {}
        self._provider_busy: set[str] = set()
        self._hint_labels: dict[str, QLabel] = {}
        self._login_rows: dict[str, QWidget] = {}
        self._login_entries: dict[str, QLineEdit] = {}
        self._open_url_btns: dict[str, QPushButton] = {}
        self._login_urls: dict[str, str] = {}
        self._login_processes: dict[str, object] = {}
        self._keepalive_stop: dict[str, threading.Event] = {}
        self._codex_callback_seen: set[str] = set()
        self._opened_urls: set[str] = set()
        self._model_combos: dict[str, QComboBox] = {}
        self._all_models: list[str] = []
        self._combo_updating = False

        self._server_status_lbl: QLabel | None = None
        self._server_detail_lbl: QLabel | None = None
        self._server_btns: list[QPushButton] = []

        # Cross-thread signal relay
        self._relay = _Relay()
        self._relay.msg.connect(self._on_relay)

        self._build_ui()
        self._refresh_status()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Panel header
        header = QFrame()
        header.setStyleSheet(
            f"background-color: {theme.BG_INPUT};"
        )
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)
        title = QLabel("Settings")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 15px; background: transparent;"
        )
        hl.addWidget(title)
        sub = QLabel("CLIProxyAPI server status and provider login")
        sub.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
        hl.addWidget(sub)
        root.addWidget(header)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background: {theme.BG_APP}; border: none; }}")

        body = QWidget()
        body.setStyleSheet(f"background: {theme.BG_APP};")
        vl = QVBoxLayout(body)
        vl.setContentsMargins(20, 16, 20, 16)
        vl.setSpacing(14)

        # --- Application section ---
        app_title = QLabel("Application")
        app_title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 16px; background: transparent;"
        )
        vl.addWidget(app_title)

        app_row = QWidget()
        app_row.setStyleSheet("background: transparent;")
        arl = QHBoxLayout(app_row)
        arl.setContentsMargins(0, 0, 0, 0)
        arl.setSpacing(8)
        restart_app_btn = QPushButton("Restart App")
        restart_app_btn.setFixedWidth(130)
        restart_app_btn.setToolTip("Restart the entire Agent Commander application")
        restart_app_btn.clicked.connect(self._do_restart_app)
        arl.addWidget(restart_app_btn)
        arl.addStretch()
        vl.addWidget(app_row)

        # Separator
        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("background: transparent; border: none; max-height: 0px;")
        vl.addWidget(sep0)

        # --- Server section ---
        server_title = QLabel("CLIProxyAPI Server")
        server_title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 16px; background: transparent;"
        )
        vl.addWidget(server_title)

        self._server_status_lbl = QLabel("Checking…")
        self._server_status_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 13px; background: transparent;"
        )
        vl.addWidget(self._server_status_lbl)

        self._server_detail_lbl = QLabel("")
        self._server_detail_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        self._server_detail_lbl.setWordWrap(True)
        vl.addWidget(self._server_detail_lbl)

        btn_row = QWidget()
        btn_row.setStyleSheet("background: transparent;")
        brl = QHBoxLayout(btn_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.setSpacing(8)
        for label, slot in [
            ("Start", self._start_server),
            ("Stop", self._stop_server),
            ("Restart", self._restart_server),
            ("Refresh", self._refresh_status),
        ]:
            b = QPushButton(label)
            b.setFixedWidth(100)
            b.clicked.connect(slot)
            brl.addWidget(b)
            self._server_btns.append(b)
        brl.addStretch()
        vl.addWidget(btn_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: transparent; border: none; max-height: 0px;")
        vl.addWidget(sep)

        # --- Provider login section ---
        login_title = QLabel("Provider Login")
        login_title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 16px; background: transparent;"
        )
        vl.addWidget(login_title)

        for key, label in _PROVIDERS:
            vl.addWidget(self._make_provider_card(key, label))

        vl.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

    def _make_provider_card(self, key: str, label: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_PANEL};"
            "  border: none; border-radius: 0px; }"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(6)

        # Top row: name | status | button
        top = QWidget()
        top.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)

        name_lbl = QLabel(label)
        name_lbl.setFixedWidth(80)
        name_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 14px; background: transparent;"
        )
        tl.addWidget(name_lbl)

        status_lbl = QLabel("…")
        status_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;"
        )
        tl.addWidget(status_lbl, stretch=1)
        self._status_labels[key] = status_lbl

        model_combo = QComboBox()
        model_combo.setFixedWidth(220)
        model_combo.setVisible(False)
        model_combo.setToolTip("Select model for this provider")
        model_combo.setStyleSheet(
            f"QComboBox {{ background-color: {theme.BG_INPUT}; color: {theme.TEXT};"
            " border: none; border-radius: 5px; padding: 3px 8px; font-size: 12px; }}"
            f"QComboBox::drop-down {{ border: none; }}"
            f"QComboBox QAbstractItemView {{ background-color: {theme.BG_INPUT};"
            f" color: {theme.TEXT}; selection-background-color: {theme.SESSION_ACTIVE_BG}; }}"
        )
        model_combo.currentIndexChanged.connect(
            lambda idx, k=key: self._on_combo_changed(k)
        )
        tl.addWidget(model_combo)
        self._model_combos[key] = model_combo

        auth_btn = QPushButton("Login")
        auth_btn.setFixedWidth(110)
        auth_btn.clicked.connect(lambda checked=False, k=key: self._run_login(k))
        tl.addWidget(auth_btn)
        self._auth_buttons[key] = auth_btn
        self._provider_connected[key] = False
        cl.addWidget(top)

        # Hint label
        hint_lbl = QLabel(_PROVIDER_LOGIN_HINTS.get(key, ""))
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
        )
        cl.addWidget(hint_lbl)
        self._hint_labels[key] = hint_lbl

        # Interactive login row (hidden by default)
        login_row = QWidget()
        login_row.setStyleSheet("background: transparent;")
        lrl = QHBoxLayout(login_row)
        lrl.setContentsMargins(0, 0, 0, 0)
        lrl.setSpacing(6)

        entry = QLineEdit()
        entry.setPlaceholderText("Login input (callback URL, mode number, etc.)")
        lrl.addWidget(entry, stretch=1)
        self._login_entries[key] = entry

        send_btn = QPushButton("Send")
        send_btn.setFixedWidth(64)
        send_btn.clicked.connect(lambda checked=False, k=key: self._send_login_input(k))
        lrl.addWidget(send_btn)

        enter_btn = QPushButton("Enter")
        enter_btn.setFixedWidth(64)
        enter_btn.clicked.connect(lambda checked=False, k=key: self._send_login_enter(k))
        lrl.addWidget(enter_btn)

        open_url_btn = QPushButton("Open URL")
        open_url_btn.setFixedWidth(90)
        open_url_btn.setEnabled(False)
        open_url_btn.clicked.connect(lambda checked=False, k=key: self._open_login_url(k))
        lrl.addWidget(open_url_btn)
        self._open_url_btns[key] = open_url_btn

        login_row.setVisible(False)
        cl.addWidget(login_row)
        self._login_rows[key] = login_row

        return card

    # ------------------------------------------------------------------
    # Relay dispatcher (runs in Qt thread)
    # ------------------------------------------------------------------

    def _on_relay(self, action: str, payload: object) -> None:
        if action == "server_text":
            text, color = payload
            if self._server_status_lbl:
                self._server_status_lbl.setText(text)
                self._server_status_lbl.setStyleSheet(
                    f"color: {color}; font-size: 13px; background: transparent;"
                )
        elif action == "server_detail":
            state = payload
            if self._server_detail_lbl:
                binary = str(state.get("binary_path", "") or "")
                config = str(state.get("config_path", "") or "")
                mode = (
                    "managed" if state.get("managed")
                    else "attached" if state.get("running") else "stopped"
                )
                lines = [f"Mode: {mode}"]
                if binary:
                    lines.append(f"Binary: {binary}")
                if config:
                    lines.append(f"Config: {config}")
                self._server_detail_lbl.setText("  ".join(lines))
        elif action == "provider_status":
            key, connected = payload
            self._apply_provider_status(key, connected)
        elif action == "server_btns":
            self._set_server_btns_enabled(bool(payload))
        elif action == "provider_hint":
            key, text, color = payload
            lbl = self._hint_labels.get(key)
            if lbl:
                lbl.setText(text)
                lbl.setStyleSheet(
                    f"color: {color}; font-size: 10px; background: transparent;"
                )
        elif action == "login_row":
            key, visible = payload
            row = self._login_rows.get(key)
            if row:
                row.setVisible(visible)
            if not visible:
                entry = self._login_entries.get(key)
                if entry:
                    entry.clear()
        elif action == "open_url_btn":
            key, enabled = payload
            btn = self._open_url_btns.get(key)
            if btn:
                btn.setEnabled(enabled)
        elif action == "login_done":
            key, rc, ok = payload
            self._finish_login(key, rc, ok)
        elif action == "model_list":
            self._populate_model_combos(payload or [])

    def _emit(self, action: str, payload: object = None) -> None:
        """Thread-safe: emit relay signal from any thread."""
        self._relay.msg.emit(action, payload)

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------

    def _refresh_status(self) -> None:
        self._emit("server_text", ("Checking…", theme.TEXT_MUTED))
        for key in self._status_labels:
            self._emit("provider_status", (key, None))  # None = "checking"

        def _check() -> None:
            manager = self._manager
            if manager is None:
                self._emit("server_text", ("No server manager (proxy mode disabled)", theme.TEXT_MUTED))
                self._emit("server_detail", {"running": False, "managed": False})
                for k in [p[0] for p in _PROVIDERS]:
                    self._emit("provider_status", (k, False))
                self._emit("server_btns", False)
                return

            state = manager.runtime_state()
            self._emit("server_detail", state)
            models = manager.health_check()
            if models is None:
                self._emit("server_text", ("Server not responding", theme.DANGER))
                for k in [p[0] for p in _PROVIDERS]:
                    self._emit("provider_status", (k, False))
                self._emit("model_list", [])
                self._emit("server_btns", True)
                return

            provider_status = manager.get_provider_status()
            managed = bool(state.get("managed"))
            mode = "managed" if managed else "attached"
            self._emit(
                "server_text",
                (f"Running ({len(models)} models, {mode})", theme.SUCCESS),
            )
            for k in [p[0] for p in _PROVIDERS]:
                self._emit("provider_status", (k, provider_status.get(k, False)))
            self._emit("model_list", models)
            self._emit("server_btns", True)

        threading.Thread(target=_check, daemon=True, name="settings-check").start()

    def _apply_provider_status(self, key: str, connected: bool | None) -> None:
        lbl = self._status_labels.get(key)
        if lbl:
            if connected is None:
                lbl.setText("…")
                lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
            elif connected:
                lbl.setText("Connected")
                lbl.setStyleSheet(f"color: {theme.SUCCESS}; font-size: 12px; background: transparent;")
                self._provider_connected[key] = True
            else:
                lbl.setText("Not connected")
                lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
                self._provider_connected[key] = False
        if connected is not None and key not in self._provider_busy:
            self._sync_auth_button(key)
            self._sync_model_combo(key)

    def _sync_auth_button(self, key: str) -> None:
        btn = self._auth_buttons.get(key)
        if btn is None:
            return
        if self._provider_connected.get(key):
            btn.setText("Disconnect")
            btn.setStyleSheet(
                "QPushButton { background-color: #992B2B; color: white; border: none;"
                " border-radius: 6px; padding: 5px 10px; font-weight: bold; }"
                "QPushButton:hover { background-color: #B33636; }"
            )
            btn.clicked.disconnect()
            btn.clicked.connect(lambda checked=False, k=key: self._run_disconnect(k))
        else:
            btn.setText("Login")
            btn.setStyleSheet("")  # revert to app stylesheet
            btn.clicked.disconnect()
            btn.clicked.connect(lambda checked=False, k=key: self._run_login(k))

    def _set_server_btns_enabled(self, enabled: bool) -> None:
        for b in self._server_btns:
            b.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Server controls
    # ------------------------------------------------------------------

    def _start_server(self) -> None:
        manager = self._manager
        if not manager:
            return
        self._set_server_btns_enabled(False)
        self._emit("server_text", ("Starting…", theme.TEXT_MUTED))

        def _work() -> None:
            ok = manager.start(timeout_s=8.0, take_over_existing=True)
            if ok:
                self._refresh_status()
            else:
                self._emit("server_text", ("Failed to start", theme.DANGER))
                self._emit("server_btns", True)

        threading.Thread(target=_work, daemon=True, name="server-start").start()

    def _stop_server(self) -> None:
        manager = self._manager
        if not manager:
            return
        self._set_server_btns_enabled(False)
        self._emit("server_text", ("Stopping…", theme.TEXT_MUTED))

        def _work() -> None:
            ok = manager.stop(force=True)
            if ok:
                self._refresh_status()
            else:
                self._emit("server_text", ("Stop failed", theme.DANGER))
                self._emit("server_btns", True)

        threading.Thread(target=_work, daemon=True, name="server-stop").start()

    def _restart_server(self) -> None:
        manager = self._manager
        if not manager:
            return
        self._set_server_btns_enabled(False)
        self._emit("server_text", ("Restarting…", theme.TEXT_MUTED))

        def _work() -> None:
            ok = manager.restart(timeout_s=8.0, force=True)
            if ok:
                self._refresh_status()
            else:
                self._emit("server_text", ("Failed to restart", theme.DANGER))
                self._emit("server_btns", True)

        threading.Thread(target=_work, daemon=True, name="server-restart").start()

    # ------------------------------------------------------------------
    # Provider login
    # ------------------------------------------------------------------

    def _run_login(self, provider: str) -> None:
        manager = self._manager
        if not manager:
            return
        btn = self._auth_buttons.get(provider)
        if btn:
            btn.setEnabled(False)
            btn.setText("Logging in…")
        self._provider_busy.add(provider)
        self._emit("server_btns", False)
        self._emit("login_row", (provider, True))
        self._emit("open_url_btn", (provider, False))
        self._login_urls.pop(provider, None)
        self._codex_callback_seen.discard(provider)
        self._opened_urls.discard(provider)

        old_stop = self._keepalive_stop.pop(provider, None)
        if old_stop:
            old_stop.set()

        def _work() -> None:
            already_connected = False
            try:
                already_connected = bool(manager.get_provider_status().get(provider, False))
            except Exception:
                pass
            if provider == "codex" and already_connected:
                self._emit("login_done", (provider, 0, True))
                return

            proc = manager.run_login_extended(
                provider,
                no_browser=True,
                capture_output=True,
                interactive_stdin=True,
                new_console=False,
            )
            self._login_processes[provider] = proc
            if proc is not None and provider == "codex":
                stop_ev = threading.Event()
                self._keepalive_stop[provider] = stop_ev
                threading.Thread(
                    target=self._codex_keepalive,
                    args=(provider, proc, stop_ev),
                    daemon=True,
                ).start()

            if proc is None:
                self._emit("login_done", (provider, 127, False))
                return

            threading.Thread(
                target=self._stream_output,
                args=(provider, proc),
                daemon=True,
            ).start()

            timeout_s = _LOGIN_TIMEOUT_S * 2 if provider == "codex" else _LOGIN_TIMEOUT_S
            deadline = time.monotonic() + timeout_s
            while True:
                rc = proc.poll()
                if rc is not None:
                    self._emit("login_done", (provider, rc, False))
                    return
                try:
                    ok = bool(manager.get_provider_status().get(provider, False))
                except Exception:
                    ok = False
                if ok and not already_connected:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                    except Exception:
                        pass
                    self._emit("login_done", (provider, 0, True))
                    return
                if time.monotonic() >= deadline:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    self._emit("login_done", (provider, 124, False))
                    return
                time.sleep(_LOGIN_POLL_S)

        threading.Thread(target=_work, daemon=True, name=f"login-{provider}").start()

    def _finish_login(self, provider: str, rc: int, ok: bool) -> None:
        self._stop_login_proc(provider)
        self._provider_busy.discard(provider)
        self._emit("login_row", (provider, False))
        self._emit("open_url_btn", (provider, False))
        self._emit("server_btns", True)
        btn = self._auth_buttons.get(provider)
        if btn:
            btn.setEnabled(True)
        self._provider_connected[provider] = ok
        self._sync_auth_button(provider)
        if ok:
            self._emit("server_text", (f"{provider.capitalize()} connected", theme.SUCCESS))
            self._emit("provider_hint", (provider, f"Connected. {_PROVIDER_LOGIN_HINTS.get(provider, '')}", theme.SUCCESS))
        elif rc == 124:
            self._emit("server_text", (f"{provider.capitalize()} login timed out", theme.DANGER))
            self._emit("provider_hint", (provider, f"Timeout. {_PROVIDER_LOGIN_HINTS.get(provider, '')}", theme.DANGER))
        elif rc not in (0, -1):
            self._emit("server_text", (f"{provider.capitalize()} login failed (exit {rc})", theme.DANGER))
        self._refresh_status()

    def _run_disconnect(self, provider: str) -> None:
        manager = self._manager
        if not manager:
            return
        btn = self._auth_buttons.get(provider)
        if btn:
            btn.setEnabled(False)
            btn.setText("Disconnecting…")
        self._provider_busy.add(provider)
        self._emit("server_text", (f"Disconnecting {provider.capitalize()}…", theme.TEXT_MUTED))

        def _work() -> None:
            ok, removed = manager.disconnect_provider(provider)
            managed = bool(manager.is_managed())
            restarted = None
            if ok and managed:
                restarted = manager.restart(timeout_s=8.0, force=True)
            self._provider_busy.discard(provider)
            self._provider_connected[provider] = False
            btn2 = self._auth_buttons.get(provider)
            if btn2:
                btn2.setEnabled(True)
            self._sync_auth_button(provider)
            if ok:
                msg = f"{provider.capitalize()} disconnected ({removed} token(s) removed)"
                color = theme.SUCCESS
            else:
                msg = f"{provider.capitalize()} disconnect failed"
                color = theme.DANGER
            self._emit("server_text", (msg, color))
            self._refresh_status()

        threading.Thread(target=_work, daemon=True, name=f"disconnect-{provider}").start()

    # ------------------------------------------------------------------
    # Login I/O helpers
    # ------------------------------------------------------------------

    def _stream_output(self, provider: str, proc: object) -> None:
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                text = str(line).strip()
                if text:
                    self._on_login_line(provider, text)
        except Exception:
            pass

    def _on_login_line(self, provider: str, line: str) -> None:
        lower = line.lower()
        match = _URL_RE.search(line)
        if match:
            url = match.group(0).rstrip(".,)")
            self._login_urls[provider] = url
            self._emit("open_url_btn", (provider, True))
            if provider not in self._opened_urls:
                self._opened_urls.add(provider)
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
        if "waiting for codex authentication callback" in lower:
            self._emit("provider_hint", (provider, "Waiting for Codex callback. Press Enter below after browser.", theme.TEXT))
        elif "paste the codex callback url" in lower:
            self._codex_callback_seen.add(provider)
            self._emit("provider_hint", (provider, "Paste callback URL below and click Send, or press Enter.", theme.TEXT))
        elif provider == "gemini" and ("choose" in lower or "select" in lower):
            self._emit("provider_hint", (provider, "Gemini expects mode selection. Enter option number and Send.", theme.TEXT))

    def _send_login_input(self, provider: str) -> None:
        entry = self._login_entries.get(provider)
        if entry is None:
            return
        value = entry.text()
        if not value:
            return
        self._write_login(provider, value + "\n")
        entry.clear()

    def _send_login_enter(self, provider: str) -> None:
        self._write_login(provider, "\n")

    def _write_login(self, provider: str, payload: str) -> None:
        proc = self._login_processes.get(provider)
        if proc is None or getattr(proc, "poll", lambda: 0)() is not None:
            return
        stdin = getattr(proc, "stdin", None)
        if stdin is None:
            return
        try:
            stdin.write(payload)
            stdin.flush()
        except Exception:
            pass

    def _open_login_url(self, provider: str) -> None:
        url = self._login_urls.get(provider, "")
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _stop_login_proc(self, provider: str) -> None:
        stop_ev = self._keepalive_stop.pop(provider, None)
        if stop_ev:
            stop_ev.set()
        self._codex_callback_seen.discard(provider)
        proc = self._login_processes.pop(provider, None)
        if proc is None:
            return
        try:
            if getattr(proc, "poll", lambda: 0)() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
        except Exception:
            pass

    def _codex_keepalive(self, provider: str, proc: object, stop: threading.Event) -> None:
        stdin = getattr(proc, "stdin", None)
        if not stdin:
            return
        while not stop.is_set():
            try:
                if getattr(proc, "poll", lambda: 0)() is not None:
                    return
                if provider in self._codex_callback_seen:
                    stdin.write("\n")
                    stdin.flush()
                    time.sleep(1.5)
                else:
                    time.sleep(0.2)
            except Exception:
                return

    # ------------------------------------------------------------------
    # Model combo helpers
    # ------------------------------------------------------------------

    def _populate_model_combos(self, all_models: list[str]) -> None:
        """Fill each provider's model combo from the server model list."""
        self._all_models = all_models
        for key, combo in self._model_combos.items():
            prefixes = _MODEL_PREFIXES.get(key, ())
            provider_models = [
                m for m in all_models
                if any(m.lower().startswith(p) for p in prefixes)
            ]
            self._combo_updating = True
            combo.clear()
            if provider_models:
                combo.addItems(provider_models)
                default = self._model_defaults.get(key, "")
                if default:
                    idx = combo.findText(default)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                    else:
                        # Configured model not in list — insert at top
                        combo.insertItem(0, default)
                        combo.setCurrentIndex(0)
            self._combo_updating = False
            self._sync_model_combo(key)

    def _sync_model_combo(self, key: str) -> None:
        """Show combo only when provider is connected and models are available."""
        combo = self._model_combos.get(key)
        if combo is None:
            return
        connected = self._provider_connected.get(key, False)
        combo.setVisible(bool(connected and combo.count() > 0))

    def _on_combo_changed(self, key: str) -> None:
        """Called when user selects a model from the dropdown."""
        if self._combo_updating:
            return
        combo = self._model_combos.get(key)
        if combo is None:
            return
        model_id = combo.currentText()
        if model_id and self._on_model_change:
            self._on_model_change(key, model_id)

    # ------------------------------------------------------------------
    # Application restart
    # ------------------------------------------------------------------

    def _do_restart_app(self) -> None:
        if self._on_restart_app:
            self._on_restart_app()

    def cleanup(self) -> None:
        for p in list(self._login_processes.keys()):
            self._stop_login_proc(p)

    def refresh(self) -> None:
        self._refresh_status()
