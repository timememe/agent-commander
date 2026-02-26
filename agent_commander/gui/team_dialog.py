"""Team panel — skill library management, inline panel style."""

from __future__ import annotations

from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.skill_store import SkillDef, SkillStore


class TeamPanel(ctk.CTkFrame):
    """Skill Library inline panel: create, edit and delete reusable skill blocks."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        skill_store: SkillStore | None = None,
        on_skill_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._skill_store = skill_store
        self._on_skill_changed = on_skill_changed

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
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
            text="Skill Library",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))

        ctk.CTkLabel(
            header,
            text="Create reusable skill blocks to inject into agent sessions",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=theme.COLOR_TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        if self._skill_store is not None:
            ctk.CTkButton(
                header,
                text="+ New Skill",
                width=110,
                height=30,
                font=(theme.FONT_FAMILY, 12),
                fg_color=theme.COLOR_ACCENT,
                command=self._new_skill,
            ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 16))

        # --- Scrollable body ---
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=theme.COLOR_BORDER,
        )
        self._scroll.grid(row=1, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        self._reload_list()

    def refresh(self) -> None:
        """Reload skill list (called when panel becomes visible)."""
        self._reload_list()

    def _reload_list(self) -> None:
        """Clear and rebuild the skill list."""
        for w in self._scroll.winfo_children():
            w.destroy()

        if self._skill_store is None:
            ctk.CTkLabel(
                self._scroll,
                text="Skill store not available.",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.COLOR_TEXT_MUTED,
            ).grid(row=0, column=0, padx=20, pady=20, sticky="w")
            return

        skills = self._skill_store.list_skills()

        if not skills:
            ctk.CTkLabel(
                self._scroll,
                text="No skills yet.\nClick '+ New Skill' to create your first skill.",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.COLOR_TEXT_MUTED,
                justify="center",
            ).grid(row=0, column=0, padx=20, pady=50, sticky="ew")
            return

        for idx, skill in enumerate(skills):
            self._build_skill_row(skill, idx)

    def _build_skill_row(self, skill: SkillDef, row: int) -> None:
        frame = ctk.CTkFrame(
            self._scroll,
            fg_color=theme.COLOR_BG_PANEL,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        frame.grid(row=row, column=0, sticky="ew", padx=0, pady=(0, 6))
        frame.grid_columnconfigure(1, weight=1)

        # Category badge
        cat = (skill.category or "General").strip()
        ctk.CTkLabel(
            frame,
            text=cat,
            font=(theme.FONT_FAMILY, 10),
            text_color=theme.COLOR_ACCENT,
            fg_color=theme.COLOR_BG_APP,
            corner_radius=4,
            width=0,
            padx=6,
            pady=2,
        ).grid(row=0, column=0, sticky="nw", padx=(12, 8), pady=(10, 0))

        # Name + description
        info = ctk.CTkFrame(frame, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(8, 8))
        info.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            info,
            text=skill.name,
            font=(theme.FONT_FAMILY, 13, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")

        if skill.description:
            ctk.CTkLabel(
                info,
                text=skill.description,
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.COLOR_TEXT_MUTED,
                anchor="w",
                wraplength=400,
                justify="left",
            ).grid(row=1, column=0, sticky="ew", pady=(2, 0))

        # Edit button
        ctk.CTkButton(
            frame,
            text="Edit",
            width=66,
            height=26,
            font=(theme.FONT_FAMILY, 11),
            fg_color="transparent",
            border_width=1,
            border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
            hover_color=theme.COLOR_BG_APP,
            command=lambda s=skill: self._edit_skill(s),
        ).grid(row=0, column=2, sticky="e", padx=(0, 6), pady=10)

        # Delete button
        ctk.CTkButton(
            frame,
            text="Delete",
            width=66,
            height=26,
            font=(theme.FONT_FAMILY, 11),
            fg_color="transparent",
            border_width=1,
            border_color=theme.COLOR_DANGER,
            text_color=theme.COLOR_DANGER,
            hover_color=theme.COLOR_BG_APP,
            command=lambda s=skill: self._delete_skill(s),
        ).grid(row=0, column=3, sticky="e", padx=(0, 12), pady=10)

    # ------------------------------------------------------------------ #
    # Actions                                                              #
    # ------------------------------------------------------------------ #

    def _new_skill(self) -> None:
        if self._skill_store is None:
            return
        EditSkillDialog(
            self.winfo_toplevel(),
            skill_store=self._skill_store,
            on_saved=self._on_saved,
        )

    def _edit_skill(self, skill: SkillDef) -> None:
        if self._skill_store is None:
            return
        EditSkillDialog(
            self.winfo_toplevel(),
            skill_store=self._skill_store,
            skill=skill,
            on_saved=self._on_saved,
        )

    def _delete_skill(self, skill: SkillDef) -> None:
        if self._skill_store is None:
            return
        if not messagebox.askyesno(
            "Delete Skill",
            f"Delete skill '{skill.name}'?\n\nThis cannot be undone.",
            parent=self.winfo_toplevel(),
        ):
            return
        self._skill_store.delete_skill(skill.id)
        self._on_saved()

    def _on_saved(self) -> None:
        """Called after any create/update/delete — refreshes list and notifies app."""
        self._reload_list()
        if self._on_skill_changed:
            self._on_skill_changed()


# Keep alias for any external references
TeamDialog = TeamPanel


# ---------------------------------------------------------------------------
# Edit / Create dialog
# ---------------------------------------------------------------------------

class EditSkillDialog(ctk.CTkToplevel):
    """Modal form for creating or editing a skill."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        skill_store: SkillStore,
        skill: SkillDef | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._skill_store = skill_store
        self._skill = skill
        self._on_saved = on_saved

        is_new = skill is None
        self.title("New Skill" if is_new else f"Edit: {skill.name}")  # type: ignore[union-attr]
        self.configure(fg_color=theme.COLOR_BG_APP)
        self.transient(master)
        theme.apply_window_icon(self)
        self.geometry("580x500")
        self.resizable(False, True)
        self.minsize(580, 420)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        self._build_form()

        if skill is not None:
            self._name_entry.insert(0, skill.name)
            self._category_entry.insert(0, skill.category)
            self._desc_entry.insert(0, skill.description)
            content = skill_store.get_content(skill.id)
            if content:
                self._content_box.insert("1.0", content)

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.lift(master)
        try:
            self.focus_force()
        except Exception:
            self.focus_set()
        self._name_entry.focus_set()
        self.grab_set()
        self.after(0, self._center_on_parent)

    def _center_on_parent(self) -> None:
        try:
            parent = self.master
            parent.update_idletasks()
            self.update_idletasks()
            px = int(parent.winfo_rootx())
            py = int(parent.winfo_rooty())
            pw = int(parent.winfo_width())
            ph = int(parent.winfo_height())
            w = int(self.winfo_width()) or int(self.winfo_reqwidth())
            h = int(self.winfo_height()) or int(self.winfo_reqheight())
            x = px + max(0, (pw - w) // 2)
            y = py + max(0, (ph - h) // 2)
            sw = int(self.winfo_screenwidth())
            sh = int(self.winfo_screenheight())
            x = max(0, min(x, sw - w - 10))
            y = max(0, min(y, sh - h - 40))
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_form(self) -> None:
        # Name
        ctk.CTkLabel(
            self,
            text="Name *",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 2))
        self._name_entry = ctk.CTkEntry(
            self,
            placeholder_text="e.g. Code Reviewer",
            height=34,
            font=(theme.FONT_FAMILY, 12),
        )
        self._name_entry.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))

        # Category + Description side by side
        meta_frame = ctk.CTkFrame(self, fg_color="transparent")
        meta_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 8))
        meta_frame.grid_columnconfigure(0, weight=1)
        meta_frame.grid_columnconfigure(1, weight=2)

        ctk.CTkLabel(
            meta_frame,
            text="Category",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(
            meta_frame,
            text="Description",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew")

        self._category_entry = ctk.CTkEntry(
            meta_frame,
            placeholder_text="e.g. Code Review",
            height=32,
            font=(theme.FONT_FAMILY, 11),
        )
        self._category_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        self._desc_entry = ctk.CTkEntry(
            meta_frame,
            placeholder_text="Short description (optional)",
            height=32,
            font=(theme.FONT_FAMILY, 11),
        )
        self._desc_entry.grid(row=1, column=1, sticky="ew")

        # Content
        ctk.CTkLabel(
            self,
            text="Content (Markdown)",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.COLOR_TEXT,
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 2))
        self._content_box = ctk.CTkTextbox(
            self,
            font=(theme.FONT_FAMILY, 12),
            fg_color=theme.COLOR_BG_PANEL,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT,
            wrap="word",
        )
        self._content_box.grid(row=4, column=0, sticky="nsew", padx=20, pady=(0, 8))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 14))
        btn_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=90,
            command=self.destroy,
        ).grid(row=0, column=1, padx=(0, 8))
        ctk.CTkButton(
            btn_frame,
            text="Save",
            width=100,
            fg_color=theme.COLOR_ACCENT,
            command=self._save,
        ).grid(row=0, column=2)

    def _save(self) -> None:
        name = self._name_entry.get().strip()
        if not name:
            self._name_entry.configure(border_color=theme.COLOR_DANGER)
            return
        category = self._category_entry.get().strip()
        description = self._desc_entry.get().strip()
        content = self._content_box.get("1.0", "end-1c").strip()

        if not content:
            if not messagebox.askyesno(
                "Empty Content",
                "Content is empty — this skill will inject no context into sessions.\n\nSave anyway?",
                parent=self,
            ):
                self._content_box.configure(border_color=theme.COLOR_DANGER)
                return
            self._content_box.configure(border_color=theme.COLOR_BORDER)

        if self._skill is None:
            self._skill_store.create_skill(name, description, category, content)
        else:
            self._skill_store.update_skill(
                self._skill.id, name, description, category, content
            )

        if self._on_saved:
            self._on_saved()
        self.destroy()
