"""File tray panel - settings + expandable directory browser."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme

if TYPE_CHECKING:
    from agent_commander.session.skill_store import SkillStore

_MAX_ENTRIES = 200


class FileTrayPanel(QWidget):
    """Right-side files panel with top settings and bottom directory tree."""

    def __init__(
        self,
        on_cwd_change: Callable[[str], None] | None = None,
        on_role_change: Callable[[str], None] | None = None,
        on_cycle_mode_change: Callable[[bool], None] | None = None,
        skill_store: "SkillStore | None" = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_cwd_change = on_cwd_change
        self._on_role_change = on_role_change
        self._on_cycle_mode_change = on_cycle_mode_change
        self._skill_store = skill_store
        self._workdir = ""
        self._expanded: set[Path] = set()
        # skill_id → combo index mapping (rebuilt in refresh_roles)
        self._role_ids: list[str] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_workdir(self, path: str) -> None:
        new_workdir = (path or "").strip()
        changed = new_workdir != self._workdir
        self._workdir = new_workdir
        self._cwd_label.setText(self._fmt_path(self._workdir))
        if changed:
            self._expanded.clear()
        self._refresh()

    def current_workdir(self) -> str:
        return self._workdir

    def set_on_cwd_change(self, callback: Callable[[str], None] | None) -> None:
        self._on_cwd_change = callback

    def current_role_id(self) -> str:
        """Return the currently selected skill_id, or '' if none."""
        idx = self._role_combo.currentIndex()
        if idx <= 0:
            return ""
        return self._role_ids[idx - 1] if idx - 1 < len(self._role_ids) else ""

    def set_role(self, skill_id: str) -> None:
        """Select a role by skill_id without emitting on_role_change."""
        if skill_id == "":
            self._role_combo.blockSignals(True)
            self._role_combo.setCurrentIndex(0)
            self._role_combo.blockSignals(False)
            return
        try:
            combo_idx = self._role_ids.index(skill_id) + 1
        except ValueError:
            combo_idx = 0
        self._role_combo.blockSignals(True)
        self._role_combo.setCurrentIndex(combo_idx)
        self._role_combo.blockSignals(False)

    def refresh_roles(self) -> None:
        """Reload skill list into the role combo (preserves current selection)."""
        current_id = self.current_role_id()
        self._role_combo.blockSignals(True)
        self._role_combo.clear()
        self._role_ids = []
        self._role_combo.addItem("— None —")
        if self._skill_store is not None:
            for skill in self._skill_store.list_skills():
                label = skill.name
                if skill.category:
                    label = f"{skill.name}  [{skill.category}]"
                self._role_combo.addItem(label)
                self._role_ids.append(skill.id)
        self._role_combo.blockSignals(False)
        self.set_role(current_id)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.setStyleSheet(
            f"QSplitter::handle {{ background-color: {theme.BORDER}; }}"
        )

        # Top: settings area (path section pinned to bottom).
        settings = QWidget()
        settings.setStyleSheet(f"background: {theme.BG_PANEL};")
        sl = QVBoxLayout(settings)
        sl.setContentsMargins(10, 10, 10, 10)
        sl.setSpacing(6)

        settings_title = QLabel("Agent Tab")
        settings_title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 12px; background: transparent;"
        )
        sl.addWidget(settings_title)

        settings_hint = QLabel("Workspace for the active chat")
        settings_hint.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
        )
        sl.addWidget(settings_hint)

        # Role selector
        role_block = QWidget()
        role_block.setStyleSheet(f"background: {theme.BG_INPUT}; border: none;")
        rb = QVBoxLayout(role_block)
        rb.setContentsMargins(8, 6, 8, 6)
        rb.setSpacing(4)

        role_head = QWidget()
        role_head.setStyleSheet("background: transparent;")
        rh = QHBoxLayout(role_head)
        rh.setContentsMargins(0, 0, 0, 0)
        rh.setSpacing(0)

        role_title = QLabel("Role")
        role_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 11px; font-weight: bold; background: transparent;"
        )
        rh.addWidget(role_title)
        rb.addWidget(role_head)

        self._role_combo = QComboBox()
        self._role_combo.setFixedHeight(28)
        self._role_combo.setStyleSheet(
            f"QComboBox {{ background: {theme.BG_PANEL}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
            " font-size: 11px; padding: 2px 8px; }"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.BG_PANEL};"
            f" color: {theme.TEXT}; border: 1px solid {theme.BORDER};"
            f" selection-background-color: {theme.SESSION_ACTIVE_BG}; }}"
        )
        self._role_combo.addItem("— None —")
        self._role_ids = []
        self._role_combo.currentIndexChanged.connect(self._on_role_selected)
        rb.addWidget(self._role_combo)
        sl.addWidget(role_block)

        # Cycle Mode toggle
        cycle_block = QWidget()
        cycle_block.setStyleSheet("background: transparent;")
        cyb = QVBoxLayout(cycle_block)
        cyb.setContentsMargins(0, 6, 0, 0)
        cyb.setSpacing(4)

        cycle_label = QLabel("Modes")
        cycle_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
        )
        cyb.addWidget(cycle_label)

        self._cycle_btn = QPushButton("⟳  Cycle Mode")
        self._cycle_btn.setFixedHeight(30)
        self._cycle_btn.setCheckable(True)
        self._cycle_btn.setChecked(False)
        self._cycle_btn.setStyleSheet(self._mode_btn_style(active=False))
        self._cycle_btn.clicked.connect(self._on_cycle_toggled)
        cyb.addWidget(self._cycle_btn)

        sl.addWidget(cycle_block)

        sl.addStretch()

        cwd_block = QWidget()
        cwd_block.setStyleSheet(f"background: {theme.BG_INPUT}; border: none;")
        cl = QVBoxLayout(cwd_block)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.setSpacing(4)

        cwd_head = QWidget()
        cwd_head.setStyleSheet("background: transparent;")
        ch = QHBoxLayout(cwd_head)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(6)

        folder_icon = QLabel("DIR")
        folder_icon.setStyleSheet("background: transparent; font-size: 10px;")
        ch.addWidget(folder_icon)

        cwd_title = QLabel("Working Folder")
        cwd_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 11px; font-weight: bold; background: transparent;"
        )
        ch.addWidget(cwd_title, stretch=1)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedHeight(22)
        browse_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.BG_PANEL}; color: {theme.TEXT_MUTED};"
            " border: none; border-radius: 6px;"
            " font-size: 11px; font-weight: bold; padding: 0 10px; }"
            f"QPushButton:hover {{ color: {theme.TEXT}; background-color: {theme.SESSION_HOVER_BG}; }}"
        )
        browse_btn.clicked.connect(self._browse_workdir)
        ch.addWidget(browse_btn)
        cl.addWidget(cwd_head)

        self._cwd_label = QLabel("No folder")
        self._cwd_label.setWordWrap(True)
        self._cwd_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
        )
        cl.addWidget(self._cwd_label)
        sl.addWidget(cwd_block)

        # Bottom: file tree (existing behavior).
        tree = QWidget()
        tree.setStyleSheet(f"background: {theme.BG_PANEL};")
        tl = QVBoxLayout(tree)
        tl.setContentsMargins(10, 10, 10, 10)
        tl.setSpacing(6)

        header = QWidget()
        header.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Files")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 13px; background: transparent;"
        )
        hl.addWidget(title)
        hl.addStretch()

        refresh_btn = QPushButton("R")
        refresh_btn.setFixedSize(26, 22)
        refresh_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            f" border: none; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}"
        )
        refresh_btn.clicked.connect(self._refresh)
        hl.addWidget(refresh_btn)
        tl.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme.BG_PANEL}; border: none; border-radius: 0px; }}"
        )
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._file_container = QWidget()
        self._file_container.setStyleSheet(f"background: {theme.BG_PANEL};")
        self._file_layout = QVBoxLayout(self._file_container)
        self._file_layout.setContentsMargins(4, 4, 4, 4)
        self._file_layout.setSpacing(1)
        self._file_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._file_container)
        tl.addWidget(scroll, stretch=1)

        split.addWidget(settings)
        split.addWidget(tree)
        split.setSizes([180, 380])
        root.addWidget(split, stretch=1)

    # ------------------------------------------------------------------
    # Directory rendering
    # ------------------------------------------------------------------

    def _clear_file_list(self) -> None:
        while self._file_layout.count():
            item = self._file_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _refresh(self) -> None:
        self._clear_file_list()

        if not self._workdir:
            self._show_info("No folder selected.")
            return

        p = Path(self._workdir)
        if not p.is_dir():
            self._show_info("Folder not found.", color=theme.DANGER)
            return

        counter = [0]

        def render_dir(dir_path: Path, indent: int) -> None:
            try:
                entries = sorted(
                    dir_path.iterdir(),
                    key=lambda e: (not e.is_dir(), e.name.lower()),
                )
            except PermissionError:
                return
            for entry in entries:
                if counter[0] >= _MAX_ENTRIES:
                    lbl = QLabel(f"... limit {_MAX_ENTRIES} reached")
                    lbl.setStyleSheet(
                        f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
                    )
                    self._file_layout.addWidget(lbl)
                    return
                self._add_row(entry, indent)
                counter[0] += 1
                if entry.is_dir() and entry in self._expanded:
                    render_dir(entry, indent + 1)

        render_dir(p, 0)

        if counter[0] == 0:
            self._show_info("Empty folder.")

    def set_cycle_mode(self, active: bool) -> None:
        """Update cycle button state without emitting callback."""
        self._cycle_btn.blockSignals(True)
        self._cycle_btn.setChecked(active)
        self._cycle_btn.setStyleSheet(self._mode_btn_style(active=active))
        self._cycle_btn.blockSignals(False)

    def _on_cycle_toggled(self, checked: bool) -> None:
        self._cycle_btn.setStyleSheet(self._mode_btn_style(active=checked))
        if self._on_cycle_mode_change:
            self._on_cycle_mode_change(checked)

    @staticmethod
    def _mode_btn_style(active: bool) -> str:
        bg = theme.SESSION_ACTIVE_BG if active else theme.BG_PANEL
        color = theme.ACCENT if active else theme.TEXT_MUTED
        border = theme.ACCENT if active else theme.BORDER
        return (
            f"QPushButton {{ background: {bg}; color: {color};"
            f" border: 1px solid {border}; border-radius: 6px;"
            " font-size: 11px; font-weight: bold; padding: 0 10px; }"
            f"QPushButton:hover {{ color: {theme.TEXT}; border-color: {theme.TEXT_MUTED}; }}"
        )

    def _on_role_selected(self, idx: int) -> None:
        skill_id = self._role_ids[idx - 1] if idx > 0 and idx - 1 < len(self._role_ids) else ""
        if self._on_role_change:
            self._on_role_change(skill_id)

    def _browse_workdir(self) -> None:
        start = self._workdir or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select working directory", start)
        if not chosen:
            return
        self.set_workdir(chosen)
        if self._on_cwd_change:
            self._on_cwd_change(self._workdir)

    def _show_info(self, text: str, color: str = "") -> None:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {color or theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        self._file_layout.addWidget(lbl)

    def _add_row(self, entry: Path, indent: int) -> None:
        is_dir = entry.is_dir()
        is_expanded = entry in self._expanded

        row = QWidget()
        row.setStyleSheet(
            "QWidget { background: transparent; border-radius: 0px; }"
            f"QWidget:hover {{ background: {theme.BG_APP}; }}"
        )
        rl = QHBoxLayout(row)
        rl.setContentsMargins(4 + indent * 14, 2, 4, 2)
        rl.setSpacing(3)

        if is_dir:
            icon_text = "-" if is_expanded else "+"
            icon_color = theme.ACCENT
            name_style = (
                f"color: {theme.ACCENT}; font-weight: bold; font-size: 11px; background: transparent;"
            )

            def _toggle(_checked: bool = False, _path: Path = entry) -> None:
                if _path in self._expanded:
                    self._expanded.discard(_path)
                else:
                    self._expanded.add(_path)
                self._refresh()

            row.mousePressEvent = lambda _e, fn=_toggle: fn()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            icon_text = "*"
            icon_color = theme.TEXT_MUTED
            name_style = f"color: {theme.TEXT}; font-size: 11px; background: transparent;"

        icon = QLabel(icon_text)
        icon.setFixedWidth(14)
        icon.setStyleSheet(
            f"color: {icon_color}; font-size: 12px; background: transparent;"
        )
        rl.addWidget(icon)

        name_lbl = QLabel(entry.name)
        name_lbl.setStyleSheet(name_style)
        rl.addWidget(name_lbl, stretch=1)

        if not is_dir:
            try:
                sz_lbl = QLabel(self._fmt_size(entry.stat().st_size))
                sz_lbl.setStyleSheet(
                    f"color: {theme.TEXT_MUTED}; font-size: 9px; background: transparent;"
                )
                rl.addWidget(sz_lbl)
            except Exception:
                pass

        self._file_layout.addWidget(row)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fmt_path(path: str) -> str:
        if not path:
            return "No folder"
        p = Path(path)
        try:
            return f"~/{p.relative_to(Path.home())}"
        except ValueError:
            return path

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        if size < 1024 ** 2:
            return f"{size // 1024}K"
        if size < 1024 ** 3:
            return f"{size // (1024 ** 2)}M"
        return f"{size // (1024 ** 3)}G"
