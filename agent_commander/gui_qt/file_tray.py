"""File tray panel - settings + expandable directory browser."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

_MAX_ENTRIES = 200


class FileTrayPanel(QWidget):
    """Right-side files panel with top settings and bottom directory tree."""

    def __init__(
        self,
        on_cwd_change: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_cwd_change = on_cwd_change
        self._workdir = ""
        self._expanded: set[Path] = set()
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
