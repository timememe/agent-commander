"""Cycle Mode settings bar — appears below InputBar when Cycle Mode is active."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from agent_commander.gui_qt import theme


class CycleControlBar(QWidget):
    """Config + status bar for Cycle Mode.

    Layout (single row):
        Every  [15] [min ▼]  ·  [∞]  [5 ] iter  ·  <status>

    Run / Stop is handled by the InputBar button.
    Call set_running(True/False) and set_status(text) from the app.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._next_run_at: float = 0.0

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_countdown)

        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def interval_seconds(self) -> int:
        val = self._spin_interval.value()
        return val * 3600 if self._combo_unit.currentText() == "hr" else val * 60

    def max_iterations(self) -> int:
        """0 = infinite."""
        return 0 if self._check_inf.isChecked() else self._spin_max.value()

    def set_running(self, running: bool) -> None:
        """Lock / unlock config fields."""
        self._spin_interval.setEnabled(not running)
        self._combo_unit.setEnabled(not running)
        self._check_inf.setEnabled(not running)
        self._spin_max.setEnabled(not running and not self._check_inf.isChecked())
        if not running:
            self._tick.stop()
            self.set_status("Ready")

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def start_countdown(self, interval_s: int) -> None:
        """Begin countdown display toward the next scheduled run."""
        self._next_run_at = time.monotonic() + interval_s
        self._tick.start()
        self._update_countdown()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(8)

        # "Every"
        row.addWidget(self._lbl("Every"))

        # Interval spinbox
        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(1, 9999)
        self._spin_interval.setValue(15)
        self._spin_interval.setFixedSize(52, 26)
        self._spin_interval.setStyleSheet(self._spinbox_style())
        row.addWidget(self._spin_interval)

        # Unit combo
        self._combo_unit = QComboBox()
        self._combo_unit.addItems(["min", "hr"])
        self._combo_unit.setFixedSize(52, 26)
        self._combo_unit.setStyleSheet(self._combo_style())
        row.addWidget(self._combo_unit)

        row.addWidget(self._sep())

        # Infinite checkbox
        self._check_inf = QCheckBox("∞")
        self._check_inf.setChecked(True)
        self._check_inf.setStyleSheet(
            f"QCheckBox {{ color: {theme.TEXT}; font-size: 14px; background: transparent; spacing: 4px; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 3px;"
            f" border: none; background: {theme.BG_APP}; }}"
            f"QCheckBox::indicator:checked {{ background: {theme.ACCENT}; }}"
        )
        self._check_inf.toggled.connect(
            lambda checked: self._spin_max.setEnabled(not checked)
        )
        row.addWidget(self._check_inf)

        # Max iterations spinbox
        self._spin_max = QSpinBox()
        self._spin_max.setRange(1, 9999)
        self._spin_max.setValue(5)
        self._spin_max.setFixedSize(52, 26)
        self._spin_max.setEnabled(False)
        self._spin_max.setStyleSheet(self._spinbox_style())
        row.addWidget(self._spin_max)

        row.addWidget(self._lbl("iter"))

        row.addWidget(self._sep())

        # Status
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        row.addWidget(self._status_lbl)

        row.addStretch()

    # ------------------------------------------------------------------
    # Countdown
    # ------------------------------------------------------------------

    def _update_countdown(self) -> None:
        remaining = max(0.0, self._next_run_at - time.monotonic())
        if remaining <= 0:
            self._tick.stop()
            return
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        self.set_status(f"Next in {mins}m {secs:02d}s" if mins else f"Next in {secs}s")

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lbl(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        return lbl

    @staticmethod
    def _sep() -> QLabel:
        sep = QLabel("·")
        sep.setStyleSheet(f"color: {theme.BORDER}; background: transparent; padding: 0 2px;")
        return sep

    @staticmethod
    def _spinbox_style() -> str:
        return (
            f"QSpinBox {{ background: {theme.BG_APP}; color: {theme.TEXT};"
            " border: none; border-radius: 4px;"
            " font-size: 12px; padding: 1px 6px; }"
            "QSpinBox::up-button, QSpinBox::down-button { width: 0; }"
            f"QSpinBox:disabled {{ color: {theme.TEXT_MUTED}; background: {theme.BG_APP}; }}"
        )

    @staticmethod
    def _combo_style() -> str:
        return (
            f"QComboBox {{ background: {theme.BG_APP}; color: {theme.TEXT};"
            " border: none; border-radius: 4px;"
            " font-size: 12px; padding: 1px 6px; }"
            "QComboBox::drop-down { border: none; width: 14px; }"
            f"QComboBox QAbstractItemView {{ background: {theme.BG_PANEL};"
            f" color: {theme.TEXT}; border: none;"
            f" selection-background-color: {theme.SESSION_ACTIVE_BG}; }}"
        )
