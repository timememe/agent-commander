"""Inline panel for creating or editing a session (Chat / Loop / Schedule)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.gui_store import ScheduleDef

if TYPE_CHECKING:
    pass

# ── Schedule helpers (reused from schedule_dialog) ────────────────────────────
_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_INTERVAL_CRON: dict[str, str] = {
    "Every 15 min":  "*/15 * * * *",
    "Every 30 min":  "*/30 * * * *",
    "Every 1 hour":  "0 * * * *",
    "Every 2 hours": "0 */2 * * *",
    "Every 3 hours": "0 */3 * * *",
    "Every 6 hours": "0 */6 * * *",
    "Every 12 hours": "0 */12 * * *",
}

_CUSTOM_KEY = "Custom…"
_TIME_OPTIONS = ["Once", "Daily", "Weekly", "Monthly"]
_ALL_REPEAT_OPTIONS = [*_TIME_OPTIONS, *_INTERVAL_CRON.keys(), _CUSTOM_KEY]


def _is_interval(repeat: str) -> bool:
    return repeat in _INTERVAL_CRON


def _build_cron_expr(repeat: str, days: list[str], hour: int, minute: int) -> str:
    if repeat in _INTERVAL_CRON:
        return _INTERVAL_CRON[repeat]
    h, m = f"{hour:02d}", f"{minute:02d}"
    if repeat in ("Once", "Daily"):
        return f"{m} {h} * * *"
    elif repeat == "Weekly":
        day_map = {"Mon": "1", "Tue": "2", "Wed": "3", "Thu": "4",
                   "Fri": "5", "Sat": "6", "Sun": "0"}
        selected = ",".join(day_map[d] for d in days if d in day_map) or "*"
        return f"{m} {h} * * {selected}"
    elif repeat == "Monthly":
        return f"{m} {h} 1 * *"
    return f"{m} {h} * * *"


def _build_display(repeat: str, days: list[str], hour: int, minute: int) -> str:
    if repeat in _INTERVAL_CRON:
        return repeat
    time_str = f"{hour:02d}:{minute:02d}"
    if repeat == "Once":
        return f"Once at {time_str}"
    elif repeat == "Daily":
        return f"Daily at {time_str}"
    elif repeat == "Weekly":
        return f"Every {', '.join(days)} at {time_str}" if days else f"Weekly at {time_str}"
    elif repeat == "Monthly":
        return f"Monthly (1st) at {time_str}"
    return f"At {time_str}"


# ── Main panel ────────────────────────────────────────────────────────────────

OnCreate = Callable[[str, "ScheduleDef | None", str], None]  # agent, sched, prompt


class NewSessionPanel(ctk.CTkFrame):
    """Inline panel for creating or editing a session."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        mode: str = "manual",
        default_agent: str = "codex",
        agents: list[str] | None = None,
        on_create: OnCreate | None = None,
        on_cancel: Callable[[], None] | None = None,
        existing_schedule: ScheduleDef | None = None,
        existing_prompt: str = "",
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._mode = mode
        self._on_create = on_create
        self._on_cancel = on_cancel
        self._is_edit = existing_schedule is not None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_ui(
            default_agent=default_agent,
            agents=agents or ["claude", "gemini", "codex"],
        )

        if existing_schedule is not None or existing_prompt:
            self._load_existing(existing_schedule, existing_prompt)

    # ── Build ─────────────────────────────────────────────────────────────

    def _build_ui(self, default_agent: str, agents: list[str]) -> None:
        _ICONS = {"manual": "💬", "loop": "↺", "schedule": "◷"}
        _TITLES = {
            "manual": "New Chat",
            "loop": "New Loop Agent",
            "schedule": "Edit Schedule" if self._is_edit else "New Schedule Agent",
        }
        _HINTS = {
            "manual": "Chat session starts immediately after creation.",
            "loop": "Agent will run in a loop until it outputs [TASK_COMPLETE].",
            "schedule": "Agent will run automatically on your configured schedule.",
        }

        icon = _ICONS.get(self._mode, "💬")
        title = _TITLES.get(self._mode, "New Chat")
        hint = _HINTS.get(self._mode, "")

        # Header card
        header = ctk.CTkFrame(
            self, fg_color=theme.COLOR_BG_INPUT,
            border_width=1, border_color=theme.COLOR_BORDER, corner_radius=8,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text=f"{icon}  {title}", anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"), text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))

        ctk.CTkLabel(
            header, text=hint, anchor="w",
            font=ctk.CTkFont(size=12), text_color=theme.COLOR_TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        # Body
        body = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=theme.COLOR_BORDER,
        )
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)

        row = 0

        # ── Agent picker ──────────────────────────────────────────────────
        ctk.CTkLabel(
            body, text="Agent", anchor="w",
            font=(theme.FONT_FAMILY, 12), text_color=theme.COLOR_TEXT,
        ).grid(row=row, column=0, sticky="w", padx=(20, 8), pady=(14, 8))
        self._agent_var = ctk.StringVar(value=default_agent)
        ctk.CTkOptionMenu(body, values=agents, variable=self._agent_var, height=32).grid(
            row=row, column=1, sticky="ew", padx=(0, 20), pady=(14, 8),
        )
        row += 1

        # ── Schedule fields ───────────────────────────────────────────────
        if self._mode == "schedule":
            # Repeat
            ctk.CTkLabel(
                body, text="Repeat", anchor="w",
                font=(theme.FONT_FAMILY, 12), text_color=theme.COLOR_TEXT,
            ).grid(row=row, column=0, sticky="w", padx=(20, 8), pady=(0, 8))
            self._repeat_var = ctk.StringVar(value="Daily")
            ctk.CTkOptionMenu(
                body, values=_ALL_REPEAT_OPTIONS,
                variable=self._repeat_var, command=self._on_repeat_change, height=30,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 20), pady=(0, 8))
            row += 1

            # Days row (weekly only)
            self._days_frame = ctk.CTkFrame(body, fg_color="transparent")
            self._days_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 8))
            self._day_vars: dict[str, ctk.BooleanVar] = {
                d: ctk.BooleanVar(value=False) for d in _DAY_NAMES
            }
            for i, day in enumerate(_DAY_NAMES):
                ctk.CTkCheckBox(
                    self._days_frame, text=day, variable=self._day_vars[day],
                    width=52, font=(theme.FONT_FAMILY, 11),
                ).grid(row=0, column=i, padx=2)
            row += 1

            # Time row (hidden for intervals / custom)
            self._time_label = ctk.CTkLabel(
                body, text="Time", anchor="w",
                font=(theme.FONT_FAMILY, 12), text_color=theme.COLOR_TEXT,
            )
            self._time_label.grid(row=row, column=0, sticky="w", padx=(20, 8), pady=(0, 8))
            self._time_row = ctk.CTkFrame(body, fg_color="transparent")
            self._time_row.grid(row=row, column=1, sticky="w", padx=(0, 20), pady=(0, 8))
            self._hour_var = ctk.StringVar(value="09")
            self._min_var = ctk.StringVar(value="00")
            ctk.CTkEntry(self._time_row, textvariable=self._hour_var, width=44, height=30,
                         font=(theme.FONT_FAMILY, 12)).pack(side="left")
            ctk.CTkLabel(self._time_row, text=":", font=(theme.FONT_FAMILY, 14, "bold"),
                         text_color=theme.COLOR_TEXT).pack(side="left", padx=2)
            ctk.CTkEntry(self._time_row, textvariable=self._min_var, width=44, height=30,
                         font=(theme.FONT_FAMILY, 12)).pack(side="left")
            row += 1

            # Custom interval row
            self._custom_label = ctk.CTkLabel(
                body, text="Every", anchor="w",
                font=(theme.FONT_FAMILY, 12), text_color=theme.COLOR_TEXT,
            )
            self._custom_label.grid(row=row, column=0, sticky="w", padx=(20, 8), pady=(0, 8))
            self._custom_row = ctk.CTkFrame(body, fg_color="transparent")
            self._custom_row.grid(row=row, column=1, sticky="w", padx=(0, 20), pady=(0, 8))
            self._custom_n_var = ctk.StringVar(value="5")
            ctk.CTkEntry(self._custom_row, textvariable=self._custom_n_var, width=60, height=30,
                         font=(theme.FONT_FAMILY, 12)).pack(side="left")
            self._custom_unit_var = ctk.StringVar(value="min")
            ctk.CTkOptionMenu(
                self._custom_row, values=["min", "hours"],
                variable=self._custom_unit_var, width=90, height=30,
                command=lambda _: self._update_next_run(),
            ).pack(side="left", padx=(6, 0))
            row += 1

            # Next run label
            ctk.CTkLabel(
                body, text="Next run", anchor="w",
                font=(theme.FONT_FAMILY, 12), text_color=theme.COLOR_TEXT,
            ).grid(row=row, column=0, sticky="w", padx=(20, 8), pady=(0, 8))
            self._next_run_label = ctk.CTkLabel(
                body, text="—", anchor="w",
                font=(theme.FONT_FAMILY, 11), text_color=theme.COLOR_TEXT_MUTED,
            )
            self._next_run_label.grid(row=row, column=1, sticky="ew", padx=(0, 20), pady=(0, 8))
            row += 1

            # Prompt
            ctk.CTkLabel(
                body, text="Prompt", anchor="nw",
                font=(theme.FONT_FAMILY, 12), text_color=theme.COLOR_TEXT,
            ).grid(row=row, column=0, sticky="nw", padx=(20, 8), pady=(0, 8))
            self._prompt_box = ctk.CTkTextbox(
                body, height=100, font=(theme.FONT_FAMILY, 12),
                fg_color=theme.COLOR_BG_PANEL, border_width=1,
                border_color=theme.COLOR_BORDER, wrap="word",
            )
            self._prompt_box.grid(row=row, column=1, sticky="ew", padx=(0, 20), pady=(0, 8))
            row += 1

            # Trigger initial state
            self._on_repeat_change("Daily")

        # ── Action buttons ────────────────────────────────────────────────
        sep = ctk.CTkFrame(body, height=1, fg_color=theme.COLOR_BORDER)
        sep.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(4, 12))
        row += 1

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.grid(row=row, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 20))
        actions.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            actions, text="Cancel", width=90,
            fg_color=theme.COLOR_BG_INPUT, hover_color=theme.COLOR_BG_PANEL,
            command=self._on_cancel_clicked,
        ).grid(row=0, column=1, padx=(0, 8))

        create_label = "Save" if self._is_edit else "Create"
        ctk.CTkButton(
            actions, text=create_label, width=110,
            fg_color=theme.COLOR_ACCENT,
            command=self._on_create_clicked,
        ).grid(row=0, column=2)

    # ── Repeat change ──────────────────────────────────────────────────────

    def _on_repeat_change(self, value: str) -> None:
        if value == "Weekly":
            self._days_frame.grid()
        else:
            self._days_frame.grid_remove()

        is_custom = (value == _CUSTOM_KEY)
        is_interval = _is_interval(value)

        if is_interval or is_custom:
            self._time_label.grid_remove()
            self._time_row.grid_remove()
        else:
            self._time_label.grid()
            self._time_row.grid()

        if is_custom:
            self._custom_label.grid()
            self._custom_row.grid()
        else:
            self._custom_label.grid_remove()
            self._custom_row.grid_remove()

        self._update_next_run()

    def _update_next_run(self) -> None:
        repeat = self._repeat_var.get()
        if _is_interval(repeat):
            self._next_run_label.configure(text=repeat)
            return
        if repeat == _CUSTOM_KEY:
            try:
                n = max(1, int(self._custom_n_var.get() or "5"))
                unit = self._custom_unit_var.get()
                self._next_run_label.configure(text=f"Every {n} {unit}")
            except Exception:
                self._next_run_label.configure(text="—")
            return
        try:
            hour = int(self._hour_var.get() or "9")
            minute = int(self._min_var.get() or "0")
            display = _build_display(
                repeat, [d for d, v in self._day_vars.items() if v.get()],
                hour, minute,
            )
            self._next_run_label.configure(text=display)
        except Exception:
            pass

    # ── Load existing ──────────────────────────────────────────────────────

    def _load_existing(self, sched: ScheduleDef | None, prompt: str) -> None:
        if sched and sched.display and hasattr(self, "_repeat_var"):
            if sched.display in _INTERVAL_CRON:
                self._repeat_var.set(sched.display)
                self._on_repeat_change(sched.display)
        if prompt and hasattr(self, "_prompt_box"):
            self._prompt_box.insert("1.0", prompt)

    # ── Actions ────────────────────────────────────────────────────────────

    def _on_create_clicked(self) -> None:
        agent = self._agent_var.get().strip().lower()

        if self._mode != "schedule":
            if self._on_create:
                self._on_create(agent, None, "")
            return

        repeat = self._repeat_var.get()
        if _is_interval(repeat):
            cron_expr = _INTERVAL_CRON[repeat]
            display = repeat
        elif repeat == _CUSTOM_KEY:
            try:
                n = max(1, int(self._custom_n_var.get() or "5"))
            except ValueError:
                n = 5
            unit = self._custom_unit_var.get()
            if unit == "min":
                cron_expr = f"*/{n} * * * *"
                display = f"Every {n} min"
            else:
                cron_expr = f"0 */{n} * * *"
                display = f"Every {n} hours"
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
        sched = ScheduleDef(cron_expr=cron_expr, display=display, enabled=True)
        if self._on_create:
            self._on_create(agent, sched, prompt)

    def _on_cancel_clicked(self) -> None:
        if self._on_cancel:
            self._on_cancel()
