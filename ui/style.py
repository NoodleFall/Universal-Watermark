from PySide6.QtCore import QTimer
from PySide6.QtGui import QPalette

# How much darker than the highlight color of the theme the main button is, in percent
# (100 = the same); the plain highlight color stands out too much in the dark theme
ACCENT_DARKER = 145
# How much darker the main button gets while pressed
ACCENT_PRESSED_DARKER = 115

# Look of the window on top of the Fusion style. Colors come from the palette,
# so the same rules work in the light and the dark theme of the system;
# @accent and @accent-pressed are set by apply_style()
STYLE_SHEET = """
QFrame#card {
    background: rgba(127, 127, 127, 0.07);
    border: 1px solid rgba(127, 127, 127, 0.28);
    border-radius: 10px;
}

QPushButton {
    background: palette(button);
    border: 1px solid rgba(127, 127, 127, 0.45);
    border-radius: 6px;
    padding: 5px 14px;
}
QPushButton:hover {
    border-color: palette(highlight);
}
QPushButton:pressed {
    background: palette(midlight);
}
QPushButton:disabled {
    border-color: rgba(127, 127, 127, 0.25);
}

QPushButton#primary {
    background: @accent;
    color: palette(highlighted-text);
    border: 1px solid @accent;
    font-weight: bold;
}
QPushButton#primary:hover {
    border-color: palette(highlighted-text);
}
QPushButton#primary:pressed {
    background: @accent-pressed;
}
QPushButton#primary:disabled {
    background: rgba(127, 127, 127, 0.3);
    border-color: transparent;
    color: palette(window);
}

QFrame#tile {
    background: rgba(127, 127, 127, 0.07);
    border: 1px solid rgba(127, 127, 127, 0.28);
    border-radius: 10px;
}
QFrame#tile:hover {
    border-color: rgba(127, 127, 127, 0.6);
}
QLabel#preview {
    background: rgba(0, 0, 0, 0.8);
    border-radius: 6px;
}
QLabel#error {
    color: #e5534b;
}
QToolButton#removeVideo {
    background: rgba(0, 0, 0, 0.55);
    color: white;
    border: none;
    border-radius: 11px;
    min-width: 22px;
    max-width: 22px;
    min-height: 22px;
    max-height: 22px;
}
QToolButton#removeVideo:hover {
    background: #c9403a;
}

QFrame#dropArea {
    border: 2px dashed transparent;
    border-radius: 12px;
}
QFrame#dropArea[empty="true"] {
    border-color: rgba(127, 127, 127, 0.4);
}
QFrame#dropArea[dragging="true"] {
    border-color: @accent;
    background: rgba(127, 127, 127, 0.08);
}
QWidget#tiles {
    background: transparent;
}

QToolButton#sectionToggle {
    border: none;
    border-radius: 6px;
    padding: 3px 6px;
}
QToolButton#sectionToggle:hover {
    background: rgba(127, 127, 127, 0.18);
}

QProgressBar {
    background: rgba(127, 127, 127, 0.22);
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
}
QProgressBar::chunk {
    background: palette(highlight);
    border-radius: 4px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(127, 127, 127, 0.45);
    border-radius: 4px;
    min-height: 30px;
    margin: 1px;
}
QScrollBar::handle:vertical:hover {
    background: rgba(127, 127, 127, 0.7);
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollArea, QScrollArea > QWidget > QWidget#settings {
    background: transparent;
    border: none;
}
"""


def apply_style(app):
    # Style the window for the current theme of the system, and again whenever it changes
    _apply_theme_colors(app)
    # The new palette of the theme is set after the change is reported
    app.styleHints().colorSchemeChanged.connect(lambda scheme: QTimer.singleShot(0, lambda: _apply_theme_colors(app)))


def _apply_theme_colors(app):
    palette = app.palette()
    accent = palette.color(QPalette.ColorRole.Highlight).darker(ACCENT_DARKER)
    app.setStyleSheet(
        STYLE_SHEET
        .replace("@accent-pressed", accent.darker(ACCENT_PRESSED_DARKER).name())
        .replace("@accent", accent.name())
    )
    # Fusion fills the boxes of checkboxes with the color of the text fields, which is too dark
    # on the cards in the dark theme; use the color of the buttons, and of the window while disabled
    checkbox = QPalette(palette)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        checkbox.setColor(group, QPalette.ColorRole.Base, palette.color(group, QPalette.ColorRole.Button))
    checkbox.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base,
        palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Window)
    )
    app.setPalette(checkbox, "QCheckBox")
