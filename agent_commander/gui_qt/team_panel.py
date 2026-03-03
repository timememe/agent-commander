"""Team panel — Skill Library management."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme
from agent_commander.session.skill_store import SkillDef, SkillStore


class TeamPanel(QWidget):
    """Skill Library panel: create, edit, delete reusable skill blocks."""

    def __init__(
        self,
        skill_store: SkillStore | None = None,
        on_skill_changed: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._skill_store = skill_store
        self._on_skill_changed = on_skill_changed
        self.setStyleSheet(f"background: {theme.BG_APP};")
        self._build_ui()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self._reload_list()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Header card
        header = QWidget()
        header.setStyleSheet(
            f"background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER}; border-radius: 8px;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(8)

        info = QWidget()
        info.setStyleSheet("background: transparent; border: none;")
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)
        title_lbl = QLabel("Skill Library")
        title_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        il.addWidget(title_lbl)
        sub_lbl = QLabel("Create reusable skill blocks to inject into agent sessions")
        sub_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        il.addWidget(sub_lbl)
        hl.addWidget(info, stretch=1)

        if self._skill_store is not None:
            new_btn = QPushButton("+ New Skill")
            new_btn.setFixedHeight(30)
            new_btn.setStyleSheet(
                f"QPushButton {{ background: {theme.ACCENT}; color: white; border: none;"
                " border-radius: 6px; font-size: 12px; font-weight: bold; padding: 0 14px; }"
                "QPushButton:hover { background: #4AABFF; }"
            )
            new_btn.clicked.connect(self._new_skill)
            hl.addWidget(new_btn)

        root.addWidget(header)

        # Scrollable skill list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._list_widget)
        root.addWidget(scroll, stretch=1)

        self._reload_list()

    def _reload_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if self._skill_store is None:
            lbl = QLabel("Skill store not available.")
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(lbl)
            return

        skills = self._skill_store.list_skills()
        if not skills:
            lbl = QLabel("No skills yet.\nClick '+ New Skill' to create your first skill.")
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            self._list_layout.addWidget(lbl)
            return

        for skill in skills:
            self._list_layout.addWidget(self._make_skill_row(skill))

    def _make_skill_row(self, skill: SkillDef) -> QWidget:
        card = QWidget()
        card.setObjectName("skill_card")
        card.setStyleSheet(
            f"QWidget#skill_card {{ background: {theme.BG_PANEL};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
        )
        rl = QHBoxLayout(card)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(10)

        cat = (skill.category or "General").strip()
        badge = QLabel(cat)
        badge.setFixedWidth(90)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: {theme.ACCENT}; background: {theme.BG_APP}; border-radius: 4px;"
            " font-size: 10px; padding: 2px 6px; border: none;"
        )
        rl.addWidget(badge)

        info = QWidget()
        info.setStyleSheet("background: transparent;")
        il = QVBoxLayout(info)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(2)
        name_lbl = QLabel(skill.name)
        name_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        il.addWidget(name_lbl)
        if skill.description:
            desc_lbl = QLabel(skill.description)
            desc_lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            desc_lbl.setWordWrap(True)
            il.addWidget(desc_lbl)
        rl.addWidget(info, stretch=1)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedSize(66, 26)
        edit_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px; font-size: 11px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}"
        )
        edit_btn.clicked.connect(lambda _, s=skill: self._edit_skill(s))
        rl.addWidget(edit_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedSize(66, 26)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.DANGER};"
            f" border: 1px solid {theme.DANGER}; border-radius: 6px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {theme.DANGER}; color: white; }}"
        )
        del_btn.clicked.connect(lambda _, s=skill: self._delete_skill(s))
        rl.addWidget(del_btn)

        return card

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _new_skill(self) -> None:
        if self._skill_store is None:
            return
        EditSkillDialog(self, skill_store=self._skill_store, on_saved=self._on_saved).exec()

    def _edit_skill(self, skill: SkillDef) -> None:
        if self._skill_store is None:
            return
        EditSkillDialog(
            self, skill_store=self._skill_store, skill=skill, on_saved=self._on_saved
        ).exec()

    def _delete_skill(self, skill: SkillDef) -> None:
        if self._skill_store is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Skill",
            f"Delete skill '{skill.name}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._skill_store.delete_skill(skill.id)
        self._on_saved()

    def _on_saved(self) -> None:
        self._reload_list()
        if self._on_skill_changed:
            self._on_skill_changed()


# ---------------------------------------------------------------------------
# Edit / Create dialog
# ---------------------------------------------------------------------------


class EditSkillDialog(QDialog):
    """Modal form for creating or editing a skill."""

    def __init__(
        self,
        parent,
        skill_store: SkillStore,
        skill: SkillDef | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._skill_store = skill_store
        self._skill = skill
        self._on_saved = on_saved
        is_new = skill is None
        self.setWindowTitle("New Skill" if is_new else f"Edit: {skill.name}")  # type: ignore[union-attr]
        self.setModal(True)
        self.resize(580, 500)
        self.setMinimumSize(520, 400)
        self.setStyleSheet(f"background: {theme.BG_APP};")
        self._build_form()
        if skill is not None:
            self._name_entry.setText(skill.name)
            self._cat_entry.setText(skill.category)
            self._desc_entry.setText(skill.description)
            content = skill_store.get_content(skill.id)
            if content:
                self._content_box.setPlainText(content)

    def _build_form(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(8)

        root.addWidget(self._field_label("Name *"))
        self._name_entry = QLineEdit()
        self._name_entry.setPlaceholderText("e.g. Code Reviewer")
        self._name_entry.setFixedHeight(34)
        self._name_entry.setStyleSheet(self._entry_style())
        root.addWidget(self._name_entry)

        meta_row = QWidget()
        meta_row.setStyleSheet("background: transparent;")
        mr = QHBoxLayout(meta_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.setSpacing(10)

        cat_col = QWidget()
        cat_col.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(cat_col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        cl.addWidget(self._field_label("Category"))
        self._cat_entry = QLineEdit()
        self._cat_entry.setPlaceholderText("e.g. Code Review")
        self._cat_entry.setFixedHeight(30)
        self._cat_entry.setStyleSheet(self._entry_style())
        cl.addWidget(self._cat_entry)
        mr.addWidget(cat_col, stretch=1)

        desc_col = QWidget()
        desc_col.setStyleSheet("background: transparent;")
        dl = QVBoxLayout(desc_col)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        dl.addWidget(self._field_label("Description"))
        self._desc_entry = QLineEdit()
        self._desc_entry.setPlaceholderText("Short description (optional)")
        self._desc_entry.setFixedHeight(30)
        self._desc_entry.setStyleSheet(self._entry_style())
        dl.addWidget(self._desc_entry)
        mr.addWidget(desc_col, stretch=2)

        root.addWidget(meta_row)

        root.addWidget(self._field_label("Content (Markdown)"))
        self._content_box = QTextEdit()
        self._content_box.setPlaceholderText("Enter skill content in Markdown…")
        self._content_box.setStyleSheet(
            f"QTextEdit {{ background: {theme.BG_PANEL}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
            " font-family: monospace; font-size: 12px; padding: 6px; }}"
        )
        root.addWidget(self._content_box, stretch=1)

        btns = QDialogButtonBox()
        cancel = btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
            " padding: 4px 16px; font-size: 12px; }"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}"
        )
        save.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: white; border: none;"
            " border-radius: 6px; padding: 4px 20px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #4AABFF; }"
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _save(self) -> None:
        name = self._name_entry.text().strip()
        if not name:
            self._name_entry.setStyleSheet(self._entry_style(error=True))
            return
        self._name_entry.setStyleSheet(self._entry_style())
        category = self._cat_entry.text().strip()
        description = self._desc_entry.text().strip()
        content = self._content_box.toPlainText().strip()
        if not content:
            reply = QMessageBox.question(
                self,
                "Empty Content",
                "Content is empty — this skill will inject no context.\n\nSave anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self._skill is None:
            self._skill_store.create_skill(name, description, category, content)
        else:
            self._skill_store.update_skill(self._skill.id, name, description, category, content)
        if self._on_saved:
            self._on_saved()
        self.accept()

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
        )
        return lbl

    @staticmethod
    def _entry_style(error: bool = False) -> str:
        bc = theme.DANGER if error else theme.BORDER
        return (
            f"QLineEdit {{ background: {theme.BG_PANEL}; color: {theme.TEXT};"
            f" border: 1px solid {bc}; border-radius: 6px;"
            " font-size: 12px; padding: 4px 8px; }}"
        )
