"""Schedule configuration dialog for schedule-mode agents."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.gui_store import ScheduleDef


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Interval options → cron expression
_INTERVAL_CRON: dict[str, str] = {
    "Every 15 min":  "*/15 * * * *",
    "Every 30 min":  "*/30 * * * *",
    "Every 1 hour":  "0 * * * *",
    "Every 2 hours": "0 */2 * * *",
    "Every 3 hours": "0 */3 * * *",
    "Every 6 hours": "0 */6 * * *",
    "Every 12 hours": "0 */12 * * *",
}

_TIME_OPTIONS = ["Once", "Daily", "Weekly", "Monthly"]
_REPEAT_OPTIONS = [*_TIME_OPTIONS, *_INTERVAL_CRON.keys()]


def _is_interval(repeat: str) -> bool:
    return repeat in _INTERVAL_CRON


def _build_cron_expr(repeat: str, days: list[str], hour: int, minute: int) -> str:
    """Convert UI selection to cron expression."""
    if repeat in _INTERVAL_CRON:
        return _INTERVAL_CRON[repeat]
    h = f"{hour:02d}"
    m = f"{minute:02d}"
    if repeat == "Once":
        return f"{m} {h} * * *"
    elif repeat == "Daily":
        return f"{m} {h} * * *"
    elif repeat == "Weekly":
        day_map = {"Mon": "1", "Tue": "2", "Wed": "3", "Thu": "4", "Fri": "5", "Sat": "6", "Sun": "0"}
        selected = ",".join(day_map[d] for d in days if d in day_map) or "*"
        return f"{m} {h} * * {selected}"
    elif repeat == "Monthly":
        return f"{m} {h} 1 * *"
    return f"{m} {h} * * *"


def _build_display(repeat: str, days: list[str], hour: int, minute: int) -> str:
    """Build human-readable schedule description."""
    if repeat in _INTERVAL_CRON:
        return repeat  # e.g. "Every 30 min"
    time_str = f"{hour:02d}:{minute:02d}"
    if repeat == "Once":
        return f"Once at {time_str}"
    elif repeat == "Daily":
        return f"Daily at {time_str}"
    elif repeat == "Weekly":
        if days:
            return f"Every {', '.join(days)} at {time_str}"
        return f"Weekly at {time_str}"
    elif repeat == "Monthly":
        return f"Monthly (1st) at {time_str}"
    return f"At {time_str}"


class ScheduleDialog(ctk.CTkToplevel):
    """Dialog for configuring a schedule for a session.

    Calls on_save(ScheduleDef, prompt_text) when confirmed.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_save: Callable[[ScheduleDef, str], None] | None = None,
        existing: ScheduleDef | None = None,
    ) -> None:
        super().__init__(master)
        self._on_save = on_save

        self.title("Schedule Agent")
        self.geometry("440x460")
        self.resizable(False, False)
        self.transient(master)
        theme.apply_window_icon(self)
        self.grab_set()
        self.configure(fg_color=theme.COLOR_BG_APP)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self, text="Schedule Agent",
            font=(theme.FONT_FAMILY, 15, "bold"),
            text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 12))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=1, column=0, sticky="ew", padx=20)
        form.grid_columnconfigure(1, weight=1)

        # Repeat
        ctk.CTkLabel(form, text="Repeat", anchor="w", font=(theme.FONT_FAMILY, 12),
                     text_color=theme.COLOR_TEXT).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._repeat_var = ctk.StringVar(value="Daily")
        self._repeat_menu = ctk.CTkOptionMenu(
            form, values=_REPEAT_OPTIONS, variable=self._repeat_var,
            command=self._on_repeat_change, height=30,
        )
        self._repeat_menu.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        # Days (weekly only)
        self._day_vars: dict[str, ctk.BooleanVar] = {d: ctk.BooleanVar(value=False) for d in _DAY_NAMES}
        self._days_frame = ctk.CTkFrame(form, fg_color="transparent")
        self._days_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for i, day in enumerate(_DAY_NAMES):
            ctk.CTkCheckBox(
                self._days_frame, text=day, variable=self._day_vars[day],
                width=52, font=(theme.FONT_FAMILY, 11),
            ).grid(row=0, column=i, padx=2)

        # Time (hidden for interval modes)
        self._time_label = ctk.CTkLabel(form, text="Time", anchor="w", font=(theme.FONT_FAMILY, 12),
                                        text_color=theme.COLOR_TEXT)
        self._time_label.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self._time_row_frame = ctk.CTkFrame(form, fg_color="transparent")
        self._time_row_frame.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(0, 8))
        self._hour_var = ctk.StringVar(value="09")
        self._min_var = ctk.StringVar(value="00")
        ctk.CTkEntry(self._time_row_frame, textvariable=self._hour_var, width=44, height=30,
                     font=(theme.FONT_FAMILY, 12)).pack(side="left")
        ctk.CTkLabel(self._time_row_frame, text=":", font=(theme.FONT_FAMILY, 14, "bold"),
                     text_color=theme.COLOR_TEXT).pack(side="left", padx=2)
        ctk.CTkEntry(self._time_row_frame, textvariable=self._min_var, width=44, height=30,
                     font=(theme.FONT_FAMILY, 12)).pack(side="left")

        # Next run (computed label)
        ctk.CTkLabel(form, text="Next run", anchor="w", font=(theme.FONT_FAMILY, 12),
                     text_color=theme.COLOR_TEXT).grid(row=3, column=0, sticky="w", pady=(0, 8))
        self._next_run_label = ctk.CTkLabel(
            form, text="—", anchor="w",
            text_color=theme.COLOR_TEXT_MUTED, font=(theme.FONT_FAMILY, 11),
        )
        self._next_run_label.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        # Prompt
        ctk.CTkLabel(form, text="Prompt", anchor="nw", font=(theme.FONT_FAMILY, 12),
                     text_color=theme.COLOR_TEXT).grid(row=4, column=0, sticky="nw", pady=(0, 4))
        self._prompt_box = ctk.CTkTextbox(
            form, height=80, font=(theme.FONT_FAMILY, 12),
            fg_color=theme.COLOR_BG_PANEL, border_width=1, border_color=theme.COLOR_BORDER,
            wrap="word",
        )
        self._prompt_box.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        # Buttons
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 20))
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(actions, text="Cancel", width=90, command=self.destroy).grid(
            row=0, column=1, sticky="e", padx=(0, 8))
        ctk.CTkButton(
            actions, text="Save Schedule", width=120, fg_color=theme.COLOR_ACCENT,
            command=self._save,
        ).grid(row=0, column=2, sticky="e")

        # Load existing if editing
        if existing:
            self._load_existing(existing)

        self._on_repeat_change(self._repeat_var.get())
        self._update_next_run()
        self.bind("<Escape>", lambda _: self.destroy())

    def _on_repeat_change(self, value: str) -> None:
        if value == "Weekly":
            self._days_frame.grid()
        else:
            self._days_frame.grid_remove()

        if _is_interval(value):
            self._time_label.grid_remove()
            self._time_row_frame.grid_remove()
        else:
            self._time_label.grid()
            self._time_row_frame.grid()

        self._update_next_run()

    def _update_next_run(self) -> None:
        repeat = self._repeat_var.get()
        if _is_interval(repeat):
            self._next_run_label.configure(text=repeat)
            return
        try:
            hour = int(self._hour_var.get() or "9")
            minute = int(self._min_var.get() or "0")
            display = _build_display(
                repeat,
                [d for d, v in self._day_vars.items() if v.get()],
                hour, minute,
            )
            self._next_run_label.configure(text=display)
        except Exception:
            pass

    def _load_existing(self, sched: ScheduleDef) -> None:
        if sched.display:
            # Try to restore interval mode from display string
            if sched.display in _INTERVAL_CRON:
                self._repeat_var.set(sched.display)

    def _save(self) -> None:
        repeat = self._repeat_var.get()
        if _is_interval(repeat):
            cron_expr = _INTERVAL_CRON[repeat]
            display = repeat
        else:
            try:
                hour = max(0, min(23, int(self._hour_var.get() or "9")))
                minute = max(0, min(59, int(self._min_var.get() or "0")))
            except ValueError:
                hour, minute = 9, 0
            days = [d for d, v in self._day_vars.items() if v.get()]
            cron_expr = _build_cron_expr(repeat, days, hour, minute)
            display = _build_display(repeat, days, hour, minute)

        prompt = self._prompt_box.get("1.0", "end-1c").strip()

        sched = ScheduleDef(
            cron_expr=cron_expr,
            display=display,
            enabled=True,
        )
        if self._on_save:
            self._on_save(sched, prompt)
        self.destroy()
