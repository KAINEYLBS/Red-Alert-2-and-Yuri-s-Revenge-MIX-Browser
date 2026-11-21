from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


# @arch mix-browser.mix-name-template-controls utility | en: Adds RA2 and Yuri's Revenge MIX name quick-fill controls and loading-priority guidance | zh: 添加 RA2 与尤里的复仇 MIX 名称快速填充控件及加载优先级说明
def add_mix_name_template_controls(
    layout: QVBoxLayout,
    name_edit: QLineEdit,
    *,
    include_mix_suffix: bool,
    quick_fill_label: str,
    ra2_button_label: str,
    yr_button_label: str,
    priority_hint: str,
) -> QLabel:
    template_row = QHBoxLayout()
    template_row.addWidget(QLabel(quick_fill_label))
    for label, prefix in (
        (ra2_button_label, "expand"),
        (yr_button_label, "expandmd"),
    ):
        button = QPushButton(label)
        button.setAutoDefault(False)

        def apply_template(_checked: bool = False, *, value: str = prefix) -> None:
            suffix = ".mix" if include_mix_suffix else ""
            name_edit.setText(f"{value}30{suffix}")
            name_edit.setCursorPosition(len(value) + 2)
            name_edit.setFocus()

        button.clicked.connect(apply_template)
        template_row.addWidget(button)
    template_row.addStretch(1)
    layout.addLayout(template_row)

    hint_label = QLabel(priority_hint)
    hint_label.setWordWrap(True)
    return hint_label
