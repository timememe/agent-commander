"""Right-side file tray panel with directory browser and drag-and-drop support."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

import customtkinter as ctk
from loguru import logger

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]

from agent_commander.gui import theme

_MAX_ENTRIES = 200
_PANEL_WIDTH = 220


class FileTrayPanel(ctk.CTkFrame):
    """Narrow right panel: directory browser for the agent's workdir.

    Accepts file/folder drag-and-drop — dropped items are copied into the
    displayed directory.  DnD is optional: if tkinterdnd2 is unavailable
    the panel still works as a read-only browser.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_status: Callable[[str], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            master,
            width=_PANEL_WIDTH,
            fg_color=theme.COLOR_BG_SIDEBAR,
            **kwargs,
        )
        self._workdir: str = ""
        self._on_status = on_status
        self._dnd_active = False  # turns True once DnD is registered
        self._expanded: set[Path] = set()  # expanded directory paths
        self._build_ui()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_workdir(self, path: str) -> None:
        """Switch the panel to display a different directory."""
        self._workdir = (path or "").strip()
        self._expanded.clear()  # reset expansion state for the new root
        self._path_label.configure(text=self._fmt_path(self._workdir))
        self._refresh()

    def enable_dnd(self) -> None:
        """Register drop targets on this panel (call once after root is mapped)."""
        if DND_FILES is None or TkinterDnD is None:
            return
        try:
            root = self.winfo_toplevel()
            if not getattr(root, "_agent_commander_dnd_ready", False):
                TkinterDnD._require(root)
                setattr(root, "_agent_commander_dnd_ready", True)

            # Register on the outer panel frame.
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.dnd_bind("<<DragLeave>>", self._on_drag_leave)

            # Also register on the inner scrollable canvas so the whole
            # file-list area is a valid drop target.
            canvas = getattr(self._file_list, "_parent_canvas", None)
            if canvas is not None:
                canvas.drop_target_register(DND_FILES)
                canvas.dnd_bind("<<Drop>>", self._on_drop)
                canvas.dnd_bind("<<DragEnter>>", self._on_drag_enter)
                canvas.dnd_bind("<<DragLeave>>", self._on_drag_leave)

            self._dnd_active = True
        except Exception as exc:
            logger.warning("DnD setup failed, drag-and-drop unavailable: {}", exc)

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Header ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 2))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Files",
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="↻",
            width=26,
            height=22,
            font=(theme.FONT_FAMILY, 14),
            fg_color="transparent",
            hover_color=theme.COLOR_BG_PANEL,
            text_color=theme.COLOR_TEXT_MUTED,
            command=self._refresh,
        ).grid(row=0, column=1, sticky="e")

        self._path_label = ctk.CTkLabel(
            header,
            text="No folder",
            font=(theme.FONT_FAMILY, 10),
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="w",
            wraplength=_PANEL_WIDTH - 20,
            justify="left",
        )
        self._path_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))

        # --- Drop zone label (inside the border frame) ---
        self._border = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_BG_PANEL,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        self._border.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 6))
        self._border.grid_columnconfigure(0, weight=1)
        self._border.grid_rowconfigure(0, weight=1)

        # Scrollable file list lives inside the border frame
        self._file_list = ctk.CTkScrollableFrame(
            self._border,
            fg_color="transparent",
            scrollbar_button_color=theme.COLOR_BORDER,
            scrollbar_button_hover_color=theme.COLOR_ACCENT,
        )
        self._file_list.grid(row=0, column=0, sticky="nsew")
        self._file_list.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ #
    # Directory listing                                                    #
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        """Re-read workdir and repopulate the file list as an expandable tree."""
        for w in self._file_list.winfo_children():
            w.destroy()

        if not self._workdir:
            self._show_info("No folder selected.\nSet a working directory\nin the input bar.")
            return

        p = Path(self._workdir)
        if not p.is_dir():
            self._show_info("Folder not found.", color=theme.COLOR_DANGER)
            return

        counter: list[int] = [0]  # mutable row counter across recursive calls

        def render_dir(dir_path: Path, indent: int) -> None:
            try:
                raw = list(dir_path.iterdir())
            except PermissionError:
                return
            entries = sorted(raw, key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in entries:
                if counter[0] >= _MAX_ENTRIES:
                    ctk.CTkLabel(
                        self._file_list,
                        text=f"… (limit {_MAX_ENTRIES} reached)",
                        font=(theme.FONT_FAMILY, 10),
                        text_color=theme.COLOR_TEXT_MUTED,
                        anchor="w",
                    ).grid(row=counter[0], column=0, padx=8, pady=(2, 4), sticky="w")
                    counter[0] += 1
                    return
                self._add_row(entry, counter[0], indent)
                counter[0] += 1
                if entry.is_dir() and entry in self._expanded:
                    render_dir(entry, indent + 1)

        render_dir(p, 0)

        if counter[0] == 0:
            self._show_info("Empty folder.\nDrop files here\nto copy them in.")

    def _show_info(self, text: str, color: str = "") -> None:
        ctk.CTkLabel(
            self._file_list,
            text=text,
            font=(theme.FONT_FAMILY, 11),
            text_color=color or theme.COLOR_TEXT_MUTED,
            justify="center",
            wraplength=_PANEL_WIDTH - 24,
        ).grid(row=0, column=0, padx=8, pady=16, sticky="ew")

    def _add_row(self, entry: Path, row: int, indent: int = 0) -> None:
        is_dir = entry.is_dir()
        is_expanded = entry in self._expanded

        # Indent: 14 px per level on the left side.
        left_pad = 2 + indent * 14

        row_frame = ctk.CTkFrame(self._file_list, fg_color="transparent", corner_radius=4)
        row_frame.grid(row=row, column=0, sticky="ew", padx=(left_pad, 2), pady=1)
        row_frame.grid_columnconfigure(1, weight=1)

        # Hover highlight
        def _enter(_e: object, f: ctk.CTkFrame = row_frame) -> None:
            f.configure(fg_color=theme.COLOR_BG_APP)

        def _leave(_e: object, f: ctk.CTkFrame = row_frame) -> None:
            f.configure(fg_color="transparent")

        row_frame.bind("<Enter>", _enter)
        row_frame.bind("<Leave>", _leave)

        # Icon — ▾ expanded dir, ▸ collapsed dir, · file
        if is_dir:
            icon_text = "▾" if is_expanded else "▸"
            icon_color = theme.COLOR_ACCENT
            name_color = theme.COLOR_ACCENT
            name_font: tuple = (theme.FONT_FAMILY, 11, "bold")

            def _toggle(_e: object = None, path: Path = entry) -> None:
                if path in self._expanded:
                    self._expanded.discard(path)
                else:
                    self._expanded.add(path)
                self._refresh()
        else:
            icon_text = "·"
            icon_color = theme.COLOR_TEXT_MUTED
            name_color = theme.COLOR_TEXT
            name_font = (theme.FONT_FAMILY, 11)
            _toggle = None  # type: ignore[assignment]

        icon = ctk.CTkLabel(
            row_frame,
            text=icon_text,
            width=16,
            font=(theme.FONT_FAMILY, 12),
            text_color=icon_color,
            cursor="hand2" if is_dir else "",
        )
        icon.grid(row=0, column=0, padx=(4, 0))
        icon.bind("<Enter>", _enter)
        icon.bind("<Leave>", _leave)

        # Name
        name_label = ctk.CTkLabel(
            row_frame,
            text=entry.name,
            font=name_font,
            text_color=name_color,
            anchor="w",
            cursor="hand2" if is_dir else "",
        )
        name_label.grid(row=0, column=1, sticky="ew", padx=(2, 4), pady=2)
        name_label.bind("<Enter>", _enter)
        name_label.bind("<Leave>", _leave)

        # Bind click to expand/collapse for directories
        if _toggle is not None:
            row_frame.bind("<Button-1>", _toggle)
            icon.bind("<Button-1>", _toggle)
            name_label.bind("<Button-1>", _toggle)
            row_frame.configure(cursor="hand2")

        # Size (files only)
        if not is_dir:
            try:
                size_text = self._fmt_size(entry.stat().st_size)
            except Exception as exc:
                logger.debug("Cannot stat {}: {}", entry, exc)
                size_text = ""
            if size_text:
                sz = ctk.CTkLabel(
                    row_frame,
                    text=size_text,
                    font=(theme.FONT_FAMILY, 9),
                    text_color=theme.COLOR_TEXT_MUTED,
                    width=34,
                    anchor="e",
                )
                sz.grid(row=0, column=2, padx=(0, 4))
                sz.bind("<Enter>", _enter)
                sz.bind("<Leave>", _leave)

    # ------------------------------------------------------------------ #
    # Drag-and-drop handlers                                               #
    # ------------------------------------------------------------------ #

    def _on_drag_enter(self, _event: object) -> None:
        self._border.configure(border_color=theme.COLOR_ACCENT)

    def _on_drag_leave(self, _event: object) -> None:
        self._border.configure(border_color=theme.COLOR_BORDER)

    def _on_drop(self, event: object) -> None:
        def _reset_border() -> None:
            self._border.configure(border_color=theme.COLOR_BORDER)

        workdir = self._workdir
        if not workdir:
            self._status("Drop failed: no working directory set")
            self.after(500, _reset_border)
            return

        dest = Path(workdir)
        data = str(getattr(event, "data", "") or "").strip()

        try:
            paths = [str(p) for p in self.tk.splitlist(data)]
        except Exception:
            paths = [data.strip("{}")]

        paths = [p.strip().strip("{}") for p in paths if p.strip().strip("{}")]
        if not paths:
            self.after(500, _reset_border)
            return

        copied, failed = 0, 0
        for src_str in paths:
            src = Path(src_str)
            if not src.exists():
                failed += 1
                continue
            try:
                if src.is_dir():
                    shutil.copytree(src, dest / src.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest / src.name)
                copied += 1
            except Exception:
                failed += 1

        if copied and not failed:
            self._status(f"Copied {copied} item(s) → {dest.name}/")
        elif copied and failed:
            self._status(f"Copied {copied}, failed to copy {failed}")
        elif failed:
            self._status(f"Failed to copy {failed} item(s)")

        self._refresh()
        self.after(500, _reset_border)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _status(self, text: str) -> None:
        if self._on_status:
            self._on_status(text)

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
