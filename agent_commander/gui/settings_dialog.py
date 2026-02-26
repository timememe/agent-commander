"""Settings panel — CLIProxyAPI server status and OAuth login, inline panel style."""

from __future__ import annotations

import re
import threading
import time
import webbrowser
from typing import TYPE_CHECKING

import customtkinter as ctk

from agent_commander.gui import theme

if TYPE_CHECKING:
    from agent_commander.providers.proxy_server import ProxyServerManager

_PROVIDERS = [
    ("claude", "Claude"),
    ("gemini", "Gemini"),
    ("codex", "Codex"),
]

_LOGIN_TIMEOUT_S = 180.0
_LOGIN_POLL_S = 0.5
_URL_RE = re.compile(r"https://\S+")

_PROVIDER_LOGIN_HINTS = {
    "claude": (
        "1) Open URL.  2) Complete browser auth.  3) If prompted, use Send/Enter below."
    ),
    "gemini": (
        "1) Open URL.  2) Complete Google auth.  3) If prompted, choose mode using input below (e.g. 1)."
    ),
    "codex": (
        "1) Open URL.  2) Complete OpenAI auth.  3) If callback prompt appears, press Enter below."
    ),
}


class SettingsPanel(ctk.CTkFrame):
    """Settings inline panel with proxy server status and provider OAuth login."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        server_manager: object | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")

        self._manager: ProxyServerManager | None = server_manager  # type: ignore[assignment]
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._auth_buttons: dict[str, ctk.CTkButton] = {}
        self._provider_connected: dict[str, bool] = {}
        self._provider_busy: set[str] = set()
        self._provider_hint_labels: dict[str, ctk.CTkLabel] = {}
        self._login_input_frames: dict[str, ctk.CTkFrame] = {}
        self._login_input_entries: dict[str, ctk.CTkEntry] = {}
        self._open_url_buttons: dict[str, ctk.CTkButton] = {}
        self._provider_login_urls: dict[str, str] = {}
        self._login_processes: dict[str, object] = {}
        self._login_keepalive_stop: dict[str, threading.Event] = {}
        self._codex_callback_prompt_seen: set[str] = set()
        self._opened_login_urls: set[str] = set()
        self._server_status_label: ctk.CTkLabel | None = None
        self._server_details_label: ctk.CTkLabel | None = None
        self._server_action_buttons: list[ctk.CTkButton] = []

        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Header card (same style as ExtensionsPanel) ---
        header = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_BG_INPUT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Settings",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))

        ctk.CTkLabel(
            header,
            text="CLIProxyAPI server status and provider login",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=theme.COLOR_TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        _scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=theme.COLOR_BORDER,
        )
        _scroll.grid(row=1, column=0, sticky="nsew")
        _scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # --- Server section ---
        server_header = ctk.CTkLabel(
            _scroll,
            text="CLIProxyAPI Server",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        )
        server_header.grid(row=row, column=0, sticky="ew", padx=20, pady=(16, 4))
        row += 1

        self._server_status_label = ctk.CTkLabel(
            _scroll,
            text="Checking...",
            font=(theme.FONT_FAMILY, 13),
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._server_status_label.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8))
        row += 1

        self._server_details_label = ctk.CTkLabel(
            _scroll,
            text="",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="w",
            justify="left",
        )
        self._server_details_label.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8))
        row += 1

        server_actions = ctk.CTkFrame(_scroll, fg_color="transparent")
        server_actions.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 12))
        server_actions.grid_columnconfigure(0, weight=0)
        server_actions.grid_columnconfigure(1, weight=0)
        server_actions.grid_columnconfigure(2, weight=0)
        server_actions.grid_columnconfigure(3, weight=1)

        start_btn = ctk.CTkButton(
            server_actions,
            text="Start Server",
            width=110,
            command=self._start_server,
        )
        start_btn.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._server_action_buttons.append(start_btn)

        stop_btn = ctk.CTkButton(
            server_actions,
            text="Stop Server",
            width=110,
            command=self._stop_server,
        )
        stop_btn.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self._server_action_buttons.append(stop_btn)

        restart_btn = ctk.CTkButton(
            server_actions,
            text="Restart Server",
            width=120,
            command=self._restart_server,
        )
        restart_btn.grid(row=0, column=2, sticky="w", padx=(0, 8))
        self._server_action_buttons.append(restart_btn)

        refresh_btn = ctk.CTkButton(
            server_actions,
            text="Refresh Status",
            width=120,
            command=self._refresh_status,
        )
        refresh_btn.grid(row=0, column=3, sticky="w")
        self._server_action_buttons.append(refresh_btn)
        row += 1

        # --- Separator ---
        sep = ctk.CTkFrame(_scroll, height=1, fg_color=theme.COLOR_BORDER)
        sep.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 12))
        row += 1

        # --- Provider login section ---
        login_header = ctk.CTkLabel(
            _scroll,
            text="Provider Login",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        )
        login_header.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 8))
        row += 1

        for key, label in _PROVIDERS:
            provider_frame = ctk.CTkFrame(
                _scroll,
                fg_color=theme.COLOR_BG_PANEL,
                border_width=1,
                border_color=theme.COLOR_BORDER,
                corner_radius=8,
            )
            provider_frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(0, 6))
            provider_frame.grid_columnconfigure(0, weight=0)
            provider_frame.grid_columnconfigure(1, weight=1)
            provider_frame.grid_columnconfigure(2, weight=0)

            name_label = ctk.CTkLabel(
                provider_frame,
                text=label,
                font=(theme.FONT_FAMILY, 14, "bold"),
                text_color=theme.COLOR_TEXT,
                width=80,
                anchor="w",
            )
            name_label.grid(row=0, column=0, sticky="w", padx=(12, 8), pady=10)

            status_label = ctk.CTkLabel(
                provider_frame,
                text="...",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.COLOR_TEXT_MUTED,
                anchor="w",
            )
            status_label.grid(row=0, column=1, sticky="w", padx=(0, 8), pady=10)
            self._status_labels[key] = status_label

            action_btn = ctk.CTkButton(
                provider_frame,
                text="Login",
                width=110,
                command=lambda k=key: self._run_login(k),
            )
            action_btn.grid(row=0, column=2, sticky="e", padx=(0, 12), pady=10)
            self._auth_buttons[key] = action_btn
            self._provider_connected[key] = False

            hint_label = ctk.CTkLabel(
                provider_frame,
                text=_PROVIDER_LOGIN_HINTS.get(key, ""),
                font=(theme.FONT_FAMILY, 10),
                text_color=theme.COLOR_TEXT_MUTED,
                anchor="w",
                justify="left",
                wraplength=500,
            )
            hint_label.grid(row=1, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
            self._provider_hint_labels[key] = hint_label

            interactive = ctk.CTkFrame(provider_frame, fg_color="transparent")
            interactive.grid(row=2, column=0, columnspan=3, sticky="ew", padx=12, pady=(0, 10))
            interactive.grid_columnconfigure(0, weight=1)
            interactive.grid_columnconfigure(1, weight=0)
            interactive.grid_columnconfigure(2, weight=0)
            interactive.grid_columnconfigure(3, weight=0)

            input_entry = ctk.CTkEntry(
                interactive,
                placeholder_text="Login input (for prompts like callback URL or mode selection)",
                height=28,
            )
            input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
            self._login_input_entries[key] = input_entry

            send_btn = ctk.CTkButton(
                interactive,
                text="Send",
                width=64,
                command=lambda k=key: self._send_login_input(k),
            )
            send_btn.grid(row=0, column=1, sticky="e", padx=(0, 6))

            enter_btn = ctk.CTkButton(
                interactive,
                text="Enter",
                width=64,
                command=lambda k=key: self._send_login_enter(k),
            )
            enter_btn.grid(row=0, column=2, sticky="e", padx=(0, 6))

            open_btn = ctk.CTkButton(
                interactive,
                text="Open URL",
                width=92,
                command=lambda k=key: self._open_login_url(k),
            )
            open_btn.grid(row=0, column=3, sticky="e")
            open_btn.configure(state="disabled")
            self._open_url_buttons[key] = open_btn

            interactive.grid_remove()
            self._login_input_frames[key] = interactive

            row += 1

        # (no close button — panel is toggled by clicking Settings in the top bar)

    def _refresh_status(self) -> None:
        """Refresh server and provider status in background."""
        if self._server_status_label:
            self._server_status_label.configure(text="Checking...")
        for label in self._status_labels.values():
            label.configure(text="...", text_color=theme.COLOR_TEXT_MUTED)

        def _check() -> None:
            manager = self._manager
            if manager is None:
                self._update_ui_no_manager()
                return

            state = manager.runtime_state()
            self.after(0, lambda s=state: self._apply_server_details(s))
            models = manager.health_check()
            if models is None:
                self._update_ui_server_down()
                return

            provider_status = manager.get_provider_status()
            self._update_ui_status(len(models), provider_status, bool(state.get("managed")))

        threading.Thread(target=_check, daemon=True, name="settings-status-check").start()

    def _update_ui_no_manager(self) -> None:
        self.after(0, lambda: self._apply_server_text(
            "No server manager (proxy mode disabled)", theme.COLOR_TEXT_MUTED
        ))
        self.after(0, lambda: self._apply_server_details({"running": False, "managed": False}))
        for key in self._status_labels:
            self.after(0, lambda k=key: self._apply_provider_text(k, False))
        self.after(0, lambda: self._set_server_actions_enabled(True))
        self.after(0, lambda: self._set_all_provider_actions_enabled(False))

    def _update_ui_server_down(self) -> None:
        self.after(0, lambda: self._apply_server_text(
            "Server not responding", theme.COLOR_DANGER
        ))
        for key in self._status_labels:
            self.after(0, lambda k=key: self._apply_provider_text(k, False))
        self.after(0, lambda: self._set_server_actions_enabled(True))

    def _update_ui_status(
        self,
        model_count: int,
        provider_status: dict[str, bool],
        managed: bool,
    ) -> None:
        mode = "managed" if managed else "attached"
        self.after(0, lambda: self._apply_server_text(
            f"Running ({model_count} models available, {mode})", theme.COLOR_SUCCESS
        ))
        for key in self._status_labels:
            connected = provider_status.get(key, False)
            self.after(0, lambda k=key, c=connected: self._apply_provider_text(k, c))
        self.after(0, lambda: self._set_server_actions_enabled(True))

    def _apply_server_text(self, text: str, color: str) -> None:
        label = self._server_status_label
        if label and label.winfo_exists():
            label.configure(text=text, text_color=color)

    def _apply_server_details(self, state: dict[str, object]) -> None:
        label = self._server_details_label
        if label is None or not label.winfo_exists():
            return
        binary = str(state.get("binary_path", "") or "")
        config = str(state.get("config_path", "") or "")
        mode = "managed" if state.get("managed") else "attached" if state.get("running") else "stopped"
        lines = [f"Mode: {mode}"]
        if binary:
            lines.append(f"Binary: {binary}")
        else:
            lines.append("Binary: not found (set proxyApi.binaryPath)")
        if config:
            lines.append(f"Config: {config}")
        label.configure(text="\n".join(lines))

    def _apply_provider_text(self, key: str, connected: bool) -> None:
        self._provider_connected[key] = connected
        label = self._status_labels.get(key)
        if label and label.winfo_exists():
            if connected:
                label.configure(text="Connected", text_color=theme.COLOR_SUCCESS)
            else:
                label.configure(text="Not connected", text_color=theme.COLOR_TEXT_MUTED)
        if key not in self._provider_busy:
            self._sync_provider_action_button(key)

    def _run_login(self, provider: str) -> None:
        """Launch OAuth login for a provider."""
        manager = self._manager
        if manager is None:
            return
        # Avoid launching a stuck/duplicate Codex login flow when already authenticated.
        if provider == "codex":
            already_connected = False
            try:
                already_connected = bool(manager.get_provider_status().get(provider, False))
            except Exception:
                already_connected = False
            if already_connected:
                self._apply_server_text(
                    "Codex already connected. Use Disconnect first if you need to re-login.",
                    theme.COLOR_TEXT_MUTED,
                )
                self._refresh_status()
                return

        btn = self._auth_buttons.get(provider)
        if btn:
            btn.configure(state="disabled", text="Logging in...")
        self._set_provider_actions_enabled(provider, False, keep_login_text=True)
        no_browser = True
        if provider == "codex":
            hint = (
                "Codex login started. URL and prompts are shown below in this window."
            )
        else:
            hint = f"{provider.capitalize()} login started. URL and prompts are shown below in this window."
        self._apply_server_text(hint, theme.COLOR_TEXT_MUTED)
        self._set_provider_hint(
            provider,
            f"Login in progress. {_PROVIDER_LOGIN_HINTS.get(provider, '')}",
            theme.COLOR_TEXT,
        )
        self._set_provider_login_controls(provider, True)
        self._set_open_url_button(provider, False)
        self._provider_login_urls.pop(provider, None)
        self._codex_callback_prompt_seen.discard(provider)
        old_stop = self._login_keepalive_stop.pop(provider, None)
        if old_stop is not None:
            old_stop.set()
        self._opened_login_urls.discard(provider)

        def _worker() -> None:
            self.after(0, lambda: self._set_server_actions_enabled(False))
            provider_connected_before = False
            try:
                provider_connected_before = bool(manager.get_provider_status().get(provider, False))
            except Exception:
                provider_connected_before = False
            proc = manager.run_login_extended(
                provider,
                no_browser=no_browser,
                capture_output=True,
                interactive_stdin=True,
                new_console=False,
            )
            self._login_processes[provider] = proc
            if proc is not None and provider == "codex":
                stop_event = threading.Event()
                self._login_keepalive_stop[provider] = stop_event
                threading.Thread(
                    target=self._codex_callback_keepalive,
                    args=(provider, proc, stop_event),
                    daemon=True,
                    name=f"login-keepalive-{provider}",
                ).start()
            return_code = -1
            connected = False
            if proc is None:
                return_code = 127
            else:
                threading.Thread(
                    target=self._stream_login_output,
                    args=(provider, proc),
                    daemon=True,
                    name=f"login-output-{provider}",
                ).start()
                timeout_s = _LOGIN_TIMEOUT_S * 2 if provider == "codex" else _LOGIN_TIMEOUT_S
                deadline = time.monotonic() + timeout_s
                while True:
                    rc = proc.poll()
                    if rc is not None:
                        return_code = rc
                        break

                    try:
                        connected_now = bool(manager.get_provider_status().get(provider, False))
                    except Exception:
                        connected_now = False
                    if connected_now and (not provider_connected_before):
                        connected = True
                        return_code = 0
                        try:
                            proc.terminate()
                            proc.wait(timeout=2.0)
                        except Exception:
                            pass
                        break

                    if time.monotonic() >= deadline:
                        return_code = 124
                        try:
                            proc.terminate()
                            proc.wait(timeout=2.0)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        break
                    time.sleep(_LOGIN_POLL_S)
            self.after(0, lambda rc=return_code, ok=connected: self._on_login_done(provider, rc, ok))

        threading.Thread(target=_worker, daemon=True, name=f"login-{provider}").start()

    def _on_login_done(self, provider: str, return_code: int = 0, connected: bool = False) -> None:
        self._stop_login_process(provider)
        self._provider_connected[provider] = connected
        self._set_provider_actions_enabled(provider, True)
        self._set_provider_login_controls(provider, False)
        self._set_open_url_button(provider, False)
        self._set_server_actions_enabled(True)
        if connected:
            self._apply_server_text(
                f"{provider.capitalize()} connected",
                theme.COLOR_SUCCESS,
            )
            self._set_provider_hint(
                provider,
                f"Connected. {_PROVIDER_LOGIN_HINTS.get(provider, '')}",
                theme.COLOR_SUCCESS,
            )
        elif return_code == 124:
            timeout_s = _LOGIN_TIMEOUT_S * 2 if provider == "codex" else _LOGIN_TIMEOUT_S
            text = f"{provider.capitalize()} login timed out after {int(timeout_s)}s"
            if provider == "codex":
                text += "; callback was not finalized"
            self._apply_server_text(text, theme.COLOR_DANGER)
            self._set_provider_hint(
                provider,
                f"Timeout. {_PROVIDER_LOGIN_HINTS.get(provider, '')}",
                theme.COLOR_DANGER,
            )
        elif return_code not in (0, -1):
            self._apply_server_text(
                f"{provider.capitalize()} login failed (exit code {return_code})",
                theme.COLOR_DANGER,
            )
            self._set_provider_hint(
                provider,
                f"Login failed. {_PROVIDER_LOGIN_HINTS.get(provider, '')}",
                theme.COLOR_DANGER,
            )
        else:
            self._set_provider_hint(
                provider,
                _PROVIDER_LOGIN_HINTS.get(provider, ""),
                theme.COLOR_TEXT_MUTED,
            )
        self._refresh_status()

    def _run_disconnect(self, provider: str) -> None:
        """Remove stored auth tokens for a provider and refresh status."""
        manager = self._manager
        if manager is None:
            return

        btn = self._auth_buttons.get(provider)
        if btn and btn.winfo_exists():
            btn.configure(state="disabled", text="Disconnecting...")
        self._set_provider_actions_enabled(provider, False)
        self._apply_server_text(f"Disconnecting {provider.capitalize()}...", theme.COLOR_TEXT_MUTED)

        def _worker() -> None:
            ok, removed = manager.disconnect_provider(provider)
            restarted: bool | None = None
            managed = bool(manager.is_managed())
            attached = bool(manager.health_check() is not None and not managed)
            if ok and managed:
                restarted = manager.restart(timeout_s=8.0, force=True)
            self.after(
                0,
                lambda success=ok, count=removed, rs=restarted, is_attached=attached:
                    self._on_disconnect_done(provider, success, count, rs, is_attached),
            )

        threading.Thread(target=_worker, daemon=True, name=f"disconnect-{provider}").start()

    def _on_disconnect_done(
        self,
        provider: str,
        success: bool,
        removed: int,
        restarted: bool | None,
        attached_running: bool,
    ) -> None:
        if success:
            self._provider_connected[provider] = False
        self._set_provider_actions_enabled(provider, True)
        if not success:
            self._apply_server_text(
                f"{provider.capitalize()} disconnect failed",
                theme.COLOR_DANGER,
            )
            self._refresh_status()
            return

        if removed > 0:
            text = f"{provider.capitalize()} disconnected ({removed} token file(s) removed)"
            color = theme.COLOR_SUCCESS
        else:
            text = f"{provider.capitalize()} had no local token files"
            color = theme.COLOR_TEXT_MUTED

        if restarted is False:
            text += "; proxy restart failed"
            color = theme.COLOR_DANGER
        elif attached_running:
            text += "; restart external proxy to apply changes immediately"

        self._apply_server_text(text, color)
        self._refresh_status()

    def _start_server(self) -> None:
        manager = self._manager
        if manager is None:
            return
        self._set_server_actions_enabled(False)
        if self._server_status_label:
            self._server_status_label.configure(text="Starting...", text_color=theme.COLOR_TEXT_MUTED)

        def _worker() -> None:
            success = manager.start(timeout_s=8.0, take_over_existing=True)
            if success:
                self.after(0, self._refresh_status)
            else:
                self.after(0, lambda: self._apply_server_text("Failed to start", theme.COLOR_DANGER))
                self.after(0, lambda: self._set_server_actions_enabled(True))

        threading.Thread(target=_worker, daemon=True, name="server-start").start()

    def _stop_server(self) -> None:
        manager = self._manager
        if manager is None:
            return
        self._set_server_actions_enabled(False)
        if self._server_status_label:
            self._server_status_label.configure(text="Stopping...", text_color=theme.COLOR_TEXT_MUTED)

        def _worker() -> None:
            stopped = manager.stop(force=True)
            if not stopped:
                self.after(0, lambda: self._apply_server_text(
                    "Stop failed (process may be external or access denied)",
                    theme.COLOR_DANGER,
                ))
                self.after(0, lambda: self._set_server_actions_enabled(True))
                return
            self.after(0, self._refresh_status)

        threading.Thread(target=_worker, daemon=True, name="server-stop").start()

    def _restart_server(self) -> None:
        """Restart CLIProxyAPI server."""
        manager = self._manager
        if manager is None:
            return

        self._set_server_actions_enabled(False)
        if self._server_status_label:
            self._server_status_label.configure(
                text="Restarting...", text_color=theme.COLOR_TEXT_MUTED
            )

        def _worker() -> None:
            success = manager.restart(timeout_s=8.0, force=True)
            if success:
                self.after(0, self._refresh_status)
            else:
                self.after(0, lambda: self._apply_server_text(
                    "Failed to restart", theme.COLOR_DANGER
                ))
                self.after(0, lambda: self._set_server_actions_enabled(True))

        threading.Thread(target=_worker, daemon=True, name="server-restart").start()

    def _set_server_actions_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in self._server_action_buttons:
            if btn.winfo_exists():
                btn.configure(state=state)

    def _sync_provider_action_button(self, provider: str) -> None:
        btn = self._auth_buttons.get(provider)
        if btn is None or not btn.winfo_exists():
            return
        connected = bool(self._provider_connected.get(provider, False))
        if connected:
            btn.configure(
                text="Disconnect",
                fg_color=theme.COLOR_DANGER,
                hover_color="#992B2B",
                command=lambda k=provider: self._run_disconnect(k),
            )
        else:
            btn.configure(
                text="Login",
                fg_color=theme.COLOR_ACCENT,
                hover_color="#1D7FD8",
                command=lambda k=provider: self._run_login(k),
            )

    def _set_provider_actions_enabled(
        self,
        provider: str,
        enabled: bool,
        keep_login_text: bool = False,
    ) -> None:
        btn = self._auth_buttons.get(provider)
        if btn is None or not btn.winfo_exists():
            return
        if enabled:
            self._provider_busy.discard(provider)
            if not keep_login_text:
                self._sync_provider_action_button(provider)
            btn.configure(state="normal")
            return
        self._provider_busy.add(provider)
        btn.configure(state="disabled")

    def _set_all_provider_actions_enabled(self, enabled: bool) -> None:
        for key in self._status_labels:
            self._set_provider_actions_enabled(key, enabled)

    def _set_provider_hint(self, provider: str, text: str, color: str) -> None:
        label = self._provider_hint_labels.get(provider)
        if label and label.winfo_exists():
            label.configure(text=text, text_color=color)

    def _set_provider_login_controls(self, provider: str, visible: bool) -> None:
        frame = self._login_input_frames.get(provider)
        if not frame or not frame.winfo_exists():
            return
        if visible:
            frame.grid()
        else:
            frame.grid_remove()
            entry = self._login_input_entries.get(provider)
            if entry and entry.winfo_exists():
                entry.delete(0, "end")

    def _set_open_url_button(self, provider: str, enabled: bool) -> None:
        btn = self._open_url_buttons.get(provider)
        if btn and btn.winfo_exists():
            btn.configure(state="normal" if enabled else "disabled")

    def _open_login_url(self, provider: str) -> None:
        url = self._provider_login_urls.get(provider, "").strip()
        if not url:
            self._apply_server_text("No login URL captured yet", theme.COLOR_TEXT_MUTED)
            return
        try:
            webbrowser.open(url)
            self._apply_server_text(f"Opened {provider.capitalize()} login URL", theme.COLOR_TEXT_MUTED)
        except Exception as exc:
            self._apply_server_text(f"Failed to open URL: {exc}", theme.COLOR_DANGER)

    def _send_login_input(self, provider: str) -> None:
        entry = self._login_input_entries.get(provider)
        if entry is None or not entry.winfo_exists():
            return
        value = entry.get()
        if value == "":
            return
        self._write_login_input(provider, value + "\n")
        entry.delete(0, "end")

    def _send_login_enter(self, provider: str) -> None:
        self._write_login_input(provider, "\n")

    def _write_login_input(self, provider: str, payload: str) -> None:
        proc = self._login_processes.get(provider)
        if proc is None or getattr(proc, "poll", lambda: 0)() is not None:
            self._apply_server_text(f"{provider.capitalize()} login process is not running", theme.COLOR_DANGER)
            return
        stdin = getattr(proc, "stdin", None)
        if stdin is None:
            self._apply_server_text("Login stdin is unavailable", theme.COLOR_DANGER)
            return
        try:
            stdin.write(payload)
            stdin.flush()
        except Exception as exc:
            self._apply_server_text(f"Failed to send input: {exc}", theme.COLOR_DANGER)

    def _stream_login_output(self, provider: str, proc: object) -> None:
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return
        try:
            while True:
                line = stream.readline()
                if not line:
                    break
                text = str(line).strip()
                if not text:
                    continue
                self.after(0, lambda p=provider, t=text: self._on_login_output_line(p, t))
        except Exception:
            return

    def _on_login_output_line(self, provider: str, line: str) -> None:
        lower = line.lower()
        match = _URL_RE.search(line)
        if match:
            url = match.group(0).rstrip(".,)")
            self._provider_login_urls[provider] = url
            self._set_open_url_button(provider, True)
            if provider not in self._opened_login_urls:
                self._opened_login_urls.add(provider)
                try:
                    webbrowser.open(url)
                    self._apply_server_text(
                        f"{provider.capitalize()} auth URL detected and opened in browser",
                        theme.COLOR_TEXT_MUTED,
                    )
                except Exception:
                    pass

        if "visit the following url" in lower:
            self._set_provider_hint(
                provider,
                "Open URL, complete auth in browser, then finish prompts below.",
                theme.COLOR_TEXT,
            )
        elif "waiting for codex authentication callback" in lower:
            self._set_provider_hint(
                provider,
                "Waiting for Codex callback. After browser success, press Enter below.",
                theme.COLOR_TEXT,
            )
        elif "paste the codex callback url" in lower:
            self._codex_callback_prompt_seen.add(provider)
            self._set_provider_hint(
                provider,
                "Paste callback URL into input and click Send, or press Enter below.",
                theme.COLOR_TEXT,
            )
        elif provider == "gemini" and ("choose" in lower or "select" in lower):
            self._set_provider_hint(
                provider,
                "Gemini expects mode selection. Enter option number below and click Send.",
                theme.COLOR_TEXT,
            )

        if "[error]" in lower or "error" in lower:
            self._apply_server_text(f"{provider.capitalize()} login: {line}", theme.COLOR_DANGER)

    def _stop_login_process(self, provider: str) -> None:
        stop_event = self._login_keepalive_stop.pop(provider, None)
        if stop_event is not None:
            stop_event.set()
        self._codex_callback_prompt_seen.discard(provider)
        proc = self._login_processes.pop(provider, None)
        if proc is None:
            return
        try:
            poll = getattr(proc, "poll", None)
            if callable(poll) and poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    proc.kill()
        except Exception:
            pass

    def _codex_callback_keepalive(
        self,
        provider: str,
        proc: object,
        stop_event: threading.Event,
    ) -> None:
        stdin = getattr(proc, "stdin", None)
        if stdin is None:
            return
        while not stop_event.is_set():
            try:
                poll = getattr(proc, "poll", None)
                if callable(poll) and poll() is not None:
                    return
                if provider in self._codex_callback_prompt_seen:
                    stdin.write("\n")
                    stdin.flush()
                    time.sleep(1.5)
                else:
                    time.sleep(0.2)
            except Exception:
                return

    def cleanup(self) -> None:
        """Stop all running login processes. Call before hiding or on app close."""
        for provider in list(self._login_processes.keys()):
            self._stop_login_process(provider)

    def _handle_close(self) -> None:
        self.cleanup()

    def refresh(self) -> None:
        """Refresh server and provider status (called when panel becomes visible)."""
        self._refresh_status()


# Keep alias for any external references
SettingsDialog = SettingsPanel
