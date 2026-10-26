# Look of the window on top of the Fusion style. Colors come from the palette,
# so the same rules work in the light and the dark theme of the system
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
    background: palette(highlight);
    color: palette(highlighted-text);
    border: 1px solid palette(highlight);
    font-weight: bold;
}
QPushButton#primary:hover {
    border-color: palette(highlighted-text);
}
QPushButton#primary:disabled {
    background: rgba(127, 127, 127, 0.3);
    border-color: transparent;
    color: palette(window);
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
