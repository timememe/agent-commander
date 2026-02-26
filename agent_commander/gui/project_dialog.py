"""Project create/edit dialog."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.project_store import ProjectMeta


class ProjectDialog(ctk.CTkToplevel):
    """Dialog for creating or editing a project.

    Usage::

        dlg = ProjectDialog(root, on_save=callback)
        # or for editing:
        dlg = ProjectDialog(root, meta=existing_meta, on_save=callback)
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        meta: ProjectMeta | None = None,
        on_save: Callable[[str, str, str], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._on_save = on_save
        self._editing = meta is not None

        title_text = "Edit Project" if self._editing else "New Project"
        self.title(title_text)
        self.geometry("420x280")
        self.resizable(False, False)
        self.transient(master)
        theme.apply_window_icon(self)
        self.grab_set()
        self.configure(fg_color=theme.COLOR_BG_APP)
        self.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            self,
            text=title_text,
            font=(theme.FONT_FAMILY, 15, "bold"),
            text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 12))

        # Form frame
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.grid(row=1, column=0, sticky="ew", padx=20)
        form.grid_columnconfigure(1, weight=1)

        # Name
        ctk.CTkLabel(form, text="Name *", anchor="w", font=(theme.FONT_FAMILY, 12),
                     text_color=theme.COLOR_TEXT).grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._name_entry = ctk.CTkEntry(form, height=30, font=(theme.FONT_FAMILY, 12))
        self._name_entry.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))
        if meta:
            self._name_entry.insert(0, meta.name)

        # Workdir
        ctk.CTkLabel(form, text="Workdir", anchor="w", font=(theme.FONT_FAMILY, 12),
                     text_color=theme.COLOR_TEXT).grid(row=1, column=0, sticky="w", pady=(0, 4))
        workdir_row = ctk.CTkFrame(form, fg_color="transparent")
        workdir_row.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))
        workdir_row.grid_columnconfigure(0, weight=1)
        self._workdir_entry = ctk.CTkEntry(workdir_row, height=30, font=(theme.FONT_FAMILY, 12))
        self._workdir_entry.grid(row=0, column=0, sticky="ew")
        if meta and meta.workdir:
            self._workdir_entry.insert(0, meta.workdir)
        ctk.CTkButton(
            workdir_row, text="Browse", width=70, height=30,
            command=self._browse_workdir,
        ).grid(row=0, column=1, sticky="e", padx=(4, 0))

        # Description
        ctk.CTkLabel(form, text="Description", anchor="w", font=(theme.FONT_FAMILY, 12),
                     text_color=theme.COLOR_TEXT).grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._desc_entry = ctk.CTkEntry(form, height=30, font=(theme.FONT_FAMILY, 12))
        self._desc_entry.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))
        if meta and meta.description:
            self._desc_entry.insert(0, meta.description)

        # Buttons
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(12, 20))
        actions.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(actions, text="Cancel", width=90, command=self.destroy).grid(
            row=0, column=1, sticky="e", padx=(0, 8)
        )
        save_text = "Save" if self._editing else "Create"
        ctk.CTkButton(
            actions, text=save_text, width=100,
            fg_color=theme.COLOR_ACCENT,
            command=self._save,
        ).grid(row=0, column=2, sticky="e")

        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Return>", lambda _: self._save())
        self._name_entry.focus_set()

    def _browse_workdir(self) -> None:
        current = self._workdir_entry.get().strip()
        selected = filedialog.askdirectory(initialdir=current or None)
        if selected:
            self._workdir_entry.delete(0, "end")
            self._workdir_entry.insert(0, selected)

    def _save(self) -> None:
        name = self._name_entry.get().strip()
        if not name:
            self._name_entry.configure(border_color=theme.COLOR_DANGER)
            return
        workdir = self._workdir_entry.get().strip()
        desc = self._desc_entry.get().strip()
        if self._on_save:
            self._on_save(name, desc, workdir)
        self.destroy()
