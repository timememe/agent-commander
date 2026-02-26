"""Input bar widget with text box, agent selector and send button."""

from __future__ import annotations

from typing import Callable
from tkinter import filedialog

import customtkinter as ctk
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - optional at runtime
    DND_FILES = None
    TkinterDnD = None

from agent_commander.gui import theme
from agent_commander.gui.agent_selector import AgentSelector

SubmitHandler = Callable[[str, str, str | None], None]
WorkdirChangeHandler = Callable[[str], None]
StopScheduleHandler = Callable[[], None]
EditScheduleHandler = Callable[[], None]


class InputBar(ctk.CTkFrame):
    """Bottom input area."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        agents: list[str],
        on_submit: SubmitHandler,
        on_workdir_change: WorkdirChangeHandler | None = None,
        on_stop_schedule: StopScheduleHandler | None = None,
        on_edit_schedule: EditScheduleHandler | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_INPUT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=10,
        )
        self._on_submit = on_submit
        self._on_workdir_change = on_workdir_change
        self._on_stop_schedule = on_stop_schedule
        self._on_edit_schedule = on_edit_schedule

        self.grid_columnconfigure(0, weight=0)  # mode badge
        self.grid_columnconfigure(1, weight=0)  # agent selector
        self.grid_columnconfigure(2, weight=1)  # workdir
        self.grid_columnconfigure(3, weight=0)  # browse
        self.grid_columnconfigure(4, weight=0)  # typing label

        self._mode_badge = ctk.CTkLabel(
            self,
            text="",
            width=0,
            height=24,
            corner_radius=12,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 10),
        )
        self._mode_badge.grid(row=0, column=0, sticky="w", padx=(10, 4), pady=8)

        self._agent_selector = AgentSelector(self, values=agents)
        self._agent_selector.grid(row=0, column=1, sticky="w", padx=(0, 4), pady=8)

        self._workdir = ctk.CTkEntry(
            self,
            placeholder_text="Working directory for this chat (optional)",
            height=30,
            font=(theme.FONT_FAMILY, 11),
        )
        self._workdir.grid(row=0, column=2, sticky="ew", padx=(0, 8), pady=8)
        self._workdir.bind("<FocusOut>", self._on_workdir_event)
        self._workdir.bind("<Return>", self._on_workdir_event)

        self._browse = ctk.CTkButton(
            self,
            text="Browse",
            width=80,
            height=30,
            command=self._browse_workdir,
        )
        self._browse.grid(row=0, column=3, sticky="e", padx=(0, 8), pady=8)

        self._typing_label = ctk.CTkLabel(
            self,
            text="",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.COLOR_TEXT_MUTED,
        )
        self._typing_label.grid(row=0, column=4, sticky="e", padx=10, pady=8)

        # Schedule info strip (row=1, hidden by default, shown in schedule mode)
        self._schedule_strip = ctk.CTkFrame(
            self, fg_color=theme.COLOR_BG_PANEL,
            corner_radius=6, border_width=1, border_color=theme.COLOR_BORDER,
        )
        self._schedule_strip.grid(row=1, column=0, columnspan=5, sticky="ew", padx=10, pady=(0, 4))
        self._schedule_strip.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._schedule_strip, text="◷", width=20,
            font=(theme.FONT_FAMILY, 13), text_color=theme.COLOR_ACCENT,
        ).grid(row=0, column=0, padx=(8, 4), pady=5, sticky="w")

        self._schedule_info_lbl = ctk.CTkLabel(
            self._schedule_strip, text="", anchor="w",
            font=(theme.FONT_FAMILY, 11), text_color=theme.COLOR_TEXT_MUTED,
        )
        self._schedule_info_lbl.grid(row=0, column=1, sticky="ew", padx=4, pady=5)

        self._run_now_btn = ctk.CTkButton(
            self._schedule_strip, text="▶ Run Now", width=90, height=26,
            fg_color=theme.COLOR_ACCENT, font=(theme.FONT_FAMILY, 11, "bold"),
            command=self._on_run_now_clicked,
        )
        self._run_now_btn.grid(row=0, column=2, padx=(4, 4), pady=5, sticky="e")

        self._edit_schedule_btn = ctk.CTkButton(
            self._schedule_strip, text="✏ Edit", width=68, height=26,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT_MUTED, hover_color=theme.COLOR_BG_APP,
            font=(theme.FONT_FAMILY, 11),
            command=self._on_edit_schedule_clicked,
        )
        self._edit_schedule_btn.grid(row=0, column=3, padx=(0, 4), pady=5, sticky="e")

        self._stop_schedule_btn = ctk.CTkButton(
            self._schedule_strip, text="⏹ Stop", width=68, height=26,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_DANGER,
            text_color=theme.COLOR_DANGER, hover_color=theme.COLOR_BG_APP,
            font=(theme.FONT_FAMILY, 11),
            command=self._on_stop_schedule_clicked,
        )
        self._stop_schedule_btn.grid(row=0, column=4, padx=(0, 8), pady=5, sticky="e")

        self._schedule_strip.grid_remove()
        self._schedule_prompt: str = ""
        self._schedule_stopped: bool = False

        self._input = ctk.CTkTextbox(
            self,
            height=90,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE),
            fg_color=theme.COLOR_BG_PANEL,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT,
            wrap="word",
        )
        self._input.grid(row=2, column=0, columnspan=4, sticky="nsew", padx=(10, 8), pady=(0, 10))
        self._input.bind("<Control-Return>", self._on_submit_hotkey)

        self._send = ctk.CTkButton(
            self,
            text="Send",
            width=90,
            height=40,
            font=(theme.FONT_FAMILY, 13, "bold"),
            fg_color=theme.COLOR_ACCENT,
            command=self._submit,
        )
        self._send.grid(row=2, column=4, sticky="se", padx=(0, 10), pady=(0, 10))

        self._setup_file_drop()

    def _on_submit_hotkey(self, _event: object) -> str:
        self._submit()
        return "break"

    def _submit(self) -> None:
        text = self._input.get("1.0", "end-1c")
        clean = text.strip()
        if not clean:
            return
        self._input.delete("1.0", "end")
        self._on_submit(clean, self._agent_selector.get(), self.get_workdir())

    def set_schedule_info(self, prompt: str, display: str, stopped: bool = False) -> None:
        """Show schedule info strip with prompt preview and controls."""
        self._schedule_prompt = prompt
        self._schedule_stopped = stopped
        prompt_preview = (prompt[:50] + "…") if len(prompt) > 50 else prompt
        label = display
        if prompt_preview:
            label = f"{display}  ·  \"{prompt_preview}\""
        if stopped:
            label = f"⏸ Stopped  ·  {label}"
        self._schedule_info_lbl.configure(text=label)
        # Show/hide controls based on stopped state
        if stopped:
            self._run_now_btn.configure(text="▶ Restart", fg_color=theme.COLOR_ACCENT)
            self._stop_schedule_btn.grid_remove()
        else:
            self._run_now_btn.configure(text="▶ Run Now", fg_color=theme.COLOR_ACCENT)
            self._stop_schedule_btn.grid()
        self._schedule_strip.grid()

    def clear_schedule_info(self) -> None:
        """Hide schedule info strip."""
        self._schedule_strip.grid_remove()
        self._schedule_prompt = ""
        self._schedule_stopped = False

    def _on_run_now_clicked(self) -> None:
        if self._schedule_stopped:
            # "▶ Restart" — toggle schedule back on via stop/restart handler
            if self._on_stop_schedule:
                self._on_stop_schedule()
            return
        prompt = self._schedule_prompt.strip()
        if not prompt:
            return
        self._on_submit(prompt, self._agent_selector.get(), self.get_workdir())

    def _on_stop_schedule_clicked(self) -> None:
        if self._on_stop_schedule:
            self._on_stop_schedule()

    def _on_edit_schedule_clicked(self) -> None:
        if self._on_edit_schedule:
            self._on_edit_schedule()

    def set_mode(self, mode: str) -> None:
        """Update the mode badge display."""
        icons = {"loop": "↺ Loop", "schedule": "◷ Schedule", "manual": ""}
        text = icons.get(mode, "")
        if text:
            self._mode_badge.configure(
                text=text,
                fg_color=theme.COLOR_ACCENT,
                text_color="#FFFFFF",
                padx=6,
            )
        else:
            self._mode_badge.configure(text="", fg_color="transparent", padx=0)

    def set_agent(self, agent: str) -> None:
        self._agent_selector.set(agent)

    def get_agent(self) -> str:
        return self._agent_selector.get()

    def get_workdir(self) -> str | None:
        value = self._workdir.get().strip()
        return value or None

    def set_workdir(self, value: str | None) -> None:
        self._workdir.delete(0, "end")
        if value:
            self._workdir.insert(0, value)

    def set_typing(self, active: bool) -> None:
        self._typing_label.configure(text="agent is typing..." if active else "")

    def _browse_workdir(self) -> None:
        current = self.get_workdir()
        selected = filedialog.askdirectory(initialdir=current or None)
        if selected:
            self.set_workdir(selected)
            self._fire_workdir_change()

    def _on_workdir_event(self, _event: object) -> None:
        self._fire_workdir_change()

    def _fire_workdir_change(self) -> None:
        if self._on_workdir_change is not None:
            self._on_workdir_change(self.get_workdir() or "")

    def _setup_file_drop(self) -> None:
        """Enable drag and drop of file paths into input box."""
        if DND_FILES is None or TkinterDnD is None:
            return

        try:
            root = self.winfo_toplevel()
            if not getattr(root, "_agent_commander_dnd_ready", False):
                TkinterDnD._require(root)
                setattr(root, "_agent_commander_dnd_ready", True)
        except Exception:
            return

        target = getattr(self._input, "_textbox", None)
        if target is None:
            return

        try:
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<Drop>>", self._on_drop_files)
        except Exception:
            return

    def _on_drop_files(self, event: object) -> str:
        data = str(getattr(event, "data", "") or "").strip()
        if not data:
            return "break"

        tk_obj = getattr(self._input, "_textbox", None)
        if tk_obj is None:
            return "break"

        try:
            files = [str(path) for path in tk_obj.tk.splitlist(data)]
        except Exception:
            files = [data.strip("{}")]

        normalized = [path.strip().strip("{}") for path in files if path.strip().strip("{}")]
        if not normalized:
            return "break"

        payload = "\n".join(f'"{path}"' if " " in path else path for path in normalized)
        current = self._input.get("1.0", "end-1c")
        prefix = "" if not current or current.endswith("\n") else "\n"
        self._input.insert("end", f"{prefix}{payload}")
        self._input.focus_set()
        return "break"
