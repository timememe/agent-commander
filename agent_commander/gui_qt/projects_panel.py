"""Projects panel — global project management."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
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
from agent_commander.session.project_store import ProjectMeta, ProjectStore


class ProjectsPanel(QWidget):
    """Projects panel: create, edit, delete global projects."""

    def __init__(
        self,
        project_store: ProjectStore | None = None,
        on_project_changed: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._project_store = project_store
        self._on_project_changed = on_project_changed
        self.setStyleSheet(f"background: {theme.BG_APP};")
        self._build_ui()

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
        title_lbl = QLabel("Projects")
        title_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 15px; font-weight: bold;"
            " background: transparent; border: none;"
        )
        il.addWidget(title_lbl)
        sub_lbl = QLabel("Track global projects and assign them to agent sessions")
        sub_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent; border: none;"
        )
        il.addWidget(sub_lbl)
        hl.addWidget(info, stretch=1)

        if self._project_store is not None:
            new_btn = QPushButton("+ New Project")
            new_btn.setFixedHeight(30)
            new_btn.setStyleSheet(
                f"QPushButton {{ background: {theme.ACCENT}; color: white; border: none;"
                " border-radius: 6px; font-size: 12px; font-weight: bold; padding: 0 14px; }}"
                "QPushButton:hover { background: #4AABFF; }"
            )
            new_btn.clicked.connect(self._new_project)
            hl.addWidget(new_btn)

        root.addWidget(header)

        # Scrollable project list
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

        if self._project_store is None:
            lbl = QLabel("Project store not available.")
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(lbl)
            return

        projects = self._project_store.list_projects()
        if not projects:
            lbl = QLabel("No projects yet.\nClick '+ New Project' to create your first project.")
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            self._list_layout.addWidget(lbl)
            return

        for project in projects:
            self._list_layout.addWidget(self._make_project_row(project))

    def _make_project_row(self, project: ProjectMeta) -> QWidget:
        card = QWidget()
        card.setObjectName("project_card")
        card.setStyleSheet(
            f"QWidget#project_card {{ background: {theme.BG_PANEL};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}"
        )
        rl = QVBoxLayout(card)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(6)

        # Top row: name + buttons
        top = QWidget()
        top.setStyleSheet("background: transparent;")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(8)

        name_lbl = QLabel(project.name)
        name_lbl.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: bold; background: transparent;"
        )
        tl.addWidget(name_lbl, stretch=1)

        # Checklist progress badge
        if project.checklist:
            done = sum(1 for item in project.checklist if item.get("done"))
            total = len(project.checklist)
            progress_lbl = QLabel(f"{done}/{total}")
            color = theme.ACCENT if done == total else theme.TEXT_MUTED
            progress_lbl.setStyleSheet(
                f"color: {color}; background: {theme.BG_APP}; border-radius: 4px;"
                " font-size: 10px; padding: 2px 8px; border: none;"
            )
            tl.addWidget(progress_lbl)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedSize(66, 26)
        edit_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px; font-size: 11px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}"
        )
        edit_btn.clicked.connect(lambda _, p=project: self._edit_project(p))
        tl.addWidget(edit_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedSize(66, 26)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.DANGER};"
            f" border: 1px solid {theme.DANGER}; border-radius: 6px; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {theme.DANGER}; color: white; }}"
        )
        del_btn.clicked.connect(lambda _, p=project: self._delete_project(p))
        tl.addWidget(del_btn)

        rl.addWidget(top)

        # Description
        if project.description:
            desc_lbl = QLabel(project.description)
            desc_lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            desc_lbl.setWordWrap(True)
            rl.addWidget(desc_lbl)

        # Workdir
        if project.workdir:
            path_lbl = QLabel(f"📁 {project.workdir}")
            path_lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
            )
            path_lbl.setWordWrap(True)
            rl.addWidget(path_lbl)

        # Checklist preview (first 3 items)
        if project.checklist:
            for item in project.checklist[:3]:
                mark = "✓" if item.get("done") else "○"
                color = theme.ACCENT if item.get("done") else theme.TEXT_MUTED
                item_lbl = QLabel(f"{mark}  {item.get('text', '')}")
                item_lbl.setStyleSheet(
                    f"color: {color}; font-size: 10px; background: transparent;"
                )
                rl.addWidget(item_lbl)
            if len(project.checklist) > 3:
                more_lbl = QLabel(f"  +{len(project.checklist) - 3} more items…")
                more_lbl.setStyleSheet(
                    f"color: {theme.TEXT_MUTED}; font-size: 10px; background: transparent;"
                )
                rl.addWidget(more_lbl)

        return card

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _new_project(self) -> None:
        if self._project_store is None:
            return
        EditProjectDialog(self, project_store=self._project_store, on_saved=self._on_saved).exec()

    def _edit_project(self, project: ProjectMeta) -> None:
        if self._project_store is None:
            return
        EditProjectDialog(
            self, project_store=self._project_store, project=project, on_saved=self._on_saved
        ).exec()

    def _delete_project(self, project: ProjectMeta) -> None:
        if self._project_store is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Project",
            f"Delete project '{project.name}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._project_store.delete_project(project.project_id)
        self._on_saved()

    def _on_saved(self) -> None:
        self._reload_list()
        if self._on_project_changed:
            self._on_project_changed()


# ---------------------------------------------------------------------------
# Edit / Create dialog
# ---------------------------------------------------------------------------


class EditProjectDialog(QDialog):
    """Modal form for creating or editing a project."""

    def __init__(
        self,
        parent,
        project_store: ProjectStore,
        project: ProjectMeta | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_store = project_store
        self._project = project
        self._on_saved = on_saved
        is_new = project is None
        self.setWindowTitle("New Project" if is_new else f"Edit: {project.name}")  # type: ignore[union-attr]
        self.setModal(True)
        self.resize(600, 560)
        self.setMinimumSize(520, 420)
        self.setStyleSheet(f"background: {theme.BG_APP};")
        self._checklist_rows: list[tuple[QCheckBox, QLineEdit, QPushButton]] = []
        self._build_form()
        if project is not None:
            self._name_entry.setText(project.name)
            self._desc_entry.setText(project.description)
            self._workdir_entry.setText(project.workdir)
            for item in project.checklist:
                self._add_checklist_row(item.get("text", ""), item.get("done", False))

    def _build_form(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(8)

        root.addWidget(self._field_label("Name *"))
        self._name_entry = QLineEdit()
        self._name_entry.setPlaceholderText("e.g. Agent Commander v1.0")
        self._name_entry.setFixedHeight(34)
        self._name_entry.setStyleSheet(self._entry_style())
        root.addWidget(self._name_entry)

        root.addWidget(self._field_label("Description"))
        self._desc_entry = QTextEdit()
        self._desc_entry.setPlaceholderText("What is this project about?")
        self._desc_entry.setFixedHeight(60)
        self._desc_entry.setStyleSheet(
            f"QTextEdit {{ background: {theme.BG_PANEL}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
            " font-size: 12px; padding: 4px 8px; }}"
        )
        root.addWidget(self._desc_entry)

        root.addWidget(self._field_label("Project Path"))
        path_row = QWidget()
        path_row.setStyleSheet("background: transparent;")
        pr = QHBoxLayout(path_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(6)
        self._workdir_entry = QLineEdit()
        self._workdir_entry.setPlaceholderText("e.g. D:/projects/my-project")
        self._workdir_entry.setFixedHeight(30)
        self._workdir_entry.setStyleSheet(self._entry_style())
        pr.addWidget(self._workdir_entry, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedHeight(30)
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px; font-size: 11px; padding: 0 10px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}"
        )
        browse_btn.clicked.connect(self._browse_workdir)
        pr.addWidget(browse_btn)
        root.addWidget(path_row)

        # Checklist section
        checklist_header = QWidget()
        checklist_header.setStyleSheet("background: transparent;")
        ch = QHBoxLayout(checklist_header)
        ch.setContentsMargins(0, 4, 0, 0)
        ch.setSpacing(8)
        ch.addWidget(self._field_label("Checklist"))
        ch.addStretch()
        add_item_btn = QPushButton("+ Add Item")
        add_item_btn.setFixedHeight(24)
        add_item_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.ACCENT};"
            " border: none; font-size: 11px; }}"
            "QPushButton:hover { text-decoration: underline; }"
        )
        add_item_btn.clicked.connect(lambda: self._add_checklist_row("", False))
        ch.addWidget(add_item_btn)
        root.addWidget(checklist_header)

        # Scrollable checklist container
        checklist_scroll = QScrollArea()
        checklist_scroll.setWidgetResizable(True)
        checklist_scroll.setFixedHeight(150)
        checklist_scroll.setStyleSheet(
            f"QScrollArea {{ background: {theme.BG_PANEL}; border: 1px solid {theme.BORDER};"
            " border-radius: 6px; }}"
        )
        checklist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._checklist_container = QWidget()
        self._checklist_container.setStyleSheet(f"background: {theme.BG_PANEL};")
        self._checklist_layout = QVBoxLayout(self._checklist_container)
        self._checklist_layout.setContentsMargins(6, 4, 6, 4)
        self._checklist_layout.setSpacing(2)
        self._checklist_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        checklist_scroll.setWidget(self._checklist_container)
        root.addWidget(checklist_scroll)

        btns = QDialogButtonBox()
        cancel = btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = btns.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER}; border-radius: 6px;"
            " padding: 4px 16px; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {theme.TEXT}; }}"
        )
        save.setStyleSheet(
            f"QPushButton {{ background: {theme.ACCENT}; color: white; border: none;"
            " border-radius: 6px; padding: 4px 20px; font-size: 12px; font-weight: bold; }}"
            "QPushButton:hover { background: #4AABFF; }"
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _add_checklist_row(self, text: str = "", done: bool = False) -> None:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        cb = QCheckBox()
        cb.setChecked(done)
        cb.setStyleSheet(
            f"QCheckBox {{ background: transparent; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; }}"
            f"QCheckBox::indicator:unchecked {{"
            f"  border: 1px solid {theme.BORDER}; border-radius: 3px;"
            f"  background: {theme.BG_APP}; }}"
            f"QCheckBox::indicator:checked {{"
            f"  border: 1px solid {theme.ACCENT}; border-radius: 3px;"
            f"  background: {theme.ACCENT}; }}"
        )
        rl.addWidget(cb)

        entry = QLineEdit(text)
        entry.setPlaceholderText("Checklist item…")
        entry.setFixedHeight(26)
        entry.setStyleSheet(
            f"QLineEdit {{ background: {theme.BG_APP}; color: {theme.TEXT};"
            f" border: 1px solid {theme.BORDER}; border-radius: 4px;"
            " font-size: 11px; padding: 2px 6px; }}"
        )
        rl.addWidget(entry, stretch=1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(22, 22)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.TEXT_MUTED};"
            " border: none; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {theme.DANGER}; }}"
        )
        rl.addWidget(del_btn)

        self._checklist_layout.addWidget(row)
        self._checklist_rows.append((cb, entry, del_btn))

        def _remove() -> None:
            row.deleteLater()
            try:
                self._checklist_rows.remove((cb, entry, del_btn))
            except ValueError:
                pass

        del_btn.clicked.connect(_remove)

    def _browse_workdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Project Directory")
        if path:
            self._workdir_entry.setText(path)

    def _save(self) -> None:
        name = self._name_entry.text().strip()
        if not name:
            self._name_entry.setStyleSheet(self._entry_style(error=True))
            return
        self._name_entry.setStyleSheet(self._entry_style())

        description = self._desc_entry.toPlainText().strip()
        workdir = self._workdir_entry.text().strip()

        checklist = []
        for cb, entry, _ in self._checklist_rows:
            text = entry.text().strip()
            if text:
                checklist.append({"text": text, "done": cb.isChecked()})

        if self._project is None:
            meta = self._project_store.create_project(name, description, workdir)
            meta.checklist = checklist
            self._project_store.update_project(meta)
        else:
            self._project.name = name
            self._project.description = description
            self._project.workdir = workdir
            self._project.checklist = checklist
            self._project_store.update_project(self._project)

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
