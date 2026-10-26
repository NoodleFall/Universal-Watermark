from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette, QValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from constants import NUMBER_INPUT_RE, NUMBER_STEP
from ui.number_input import format_number, parse_number

# Width of a number field, and of the text shown in its place while its value is automatic
NUMBER_FIELD_WIDTH = 90
# Least width of the main menus, so they line up
MENU_MIN_WIDTH = 260


class InputLock:
    """
    Inputs that are locked while rendering. Items are widgets, or fields with their own
    set_enabled(); after unlocking, the on_unlock callbacks restore the states that depend
    on other settings (e.g. a menu that is only used while a checkbox is on).
    """

    def __init__(self):
        self.locked = False
        self._items = []
        self._unlock_callbacks = []

    def add(self, *items):
        self._items.extend(items)

    def on_unlock(self, callback):
        self._unlock_callbacks.append(callback)

    def set_enabled(self, enabled):
        self.locked = not enabled
        for item in self._items:
            if hasattr(item, "set_enabled"):
                item.set_enabled(enabled)
            else:
                item.setEnabled(enabled)
        if enabled:
            for callback in self._unlock_callbacks:
                callback()


# Each bind_* function shows the variable in the widget and keeps both in sync both ways

def bind_line_edit(edit, var):
    edit.setText(var.get())
    edit.textChanged.connect(var.set)

    def show(value):
        # Setting the same text would move the cursor to the end
        if edit.text() != value:
            edit.setText(value)

    var.changed.connect(show)


def bind_checkbox(checkbox, var):
    checkbox.setChecked(var.get())
    checkbox.toggled.connect(var.set)
    var.changed.connect(checkbox.setChecked)


def bind_combo(combo, var):
    combo.setCurrentText(var.get())
    combo.currentTextChanged.connect(var.set)
    var.changed.connect(combo.setCurrentText)


def bind_spinbox(spin, var):
    # The variable keeps the number as text, e.g. "12.5", the way it is saved in the settings
    number = parse_number(var.get())
    if number is not None:
        spin.setValue(number)
    spin.valueChanged.connect(lambda value: var.set(format_number(value)))

    def show(value):
        number = parse_number(value)
        if number is not None:
            spin.setValue(number)

    var.changed.connect(show)


def set_secondary(label):
    # Hints and placeholders are shown in the lighter color of the theme
    label.setForegroundRole(QPalette.ColorRole.PlaceholderText)


class NumberSpinBox(QDoubleSpinBox):
    """
    Number up to max_value with two decimals at most, shown without trailing zeros; a comma
    works as the decimal point too. Above zero, or zero too with allow_zero. Typing a number
    above the maximum turns it into the maximum. The mouse wheel changes the number only
    while the field has the cursor, otherwise it scrolls the settings.
    """

    def __init__(self, max_value, allow_zero=False):
        super().__init__()
        self.allow_zero = allow_zero
        self.setDecimals(2)
        self.setRange(0 if allow_zero else 0.01, max_value)
        self.setSingleStep(NUMBER_STEP)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedWidth(NUMBER_FIELD_WIDTH)

    def textFromValue(self, value):
        return format_number(value)

    def valueFromText(self, text):
        return parse_number(text) or 0

    def validate(self, text, pos):
        if not NUMBER_INPUT_RE.fullmatch(text):
            return QValidator.State.Invalid
        number = parse_number(text)
        if number is None or number < self.minimum():
            return QValidator.State.Intermediate
        if number > self.maximum():
            # Too large: the field shows the maximum instead
            text = format_number(self.maximum())
            return QValidator.State.Acceptable, text, len(text)
        return QValidator.State.Acceptable

    def stepBy(self, steps):
        # Without allow_zero, stepping down to zero or below keeps the current value
        if not self.allow_zero and self.value() + steps * self.singleStep() <= 0:
            return
        super().stepBy(steps)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            # Let the settings scroll instead
            event.ignore()


class NumberField:
    """
    Number field up to max_value with an optional hint after it, added to the inputs of a
    settings row. The number is above zero, or zero too with allow_zero.
    """

    def __init__(self, inputs, lock, variable, max_value, hint=None, allow_zero=False):
        self.variable = variable
        self.spin = NumberSpinBox(max_value, allow_zero)
        bind_spinbox(self.spin, variable)
        inputs.layout().addWidget(self._field_widget())

        self.hint_label = None
        if hint is not None:
            self.hint_label = QLabel(hint)
            set_secondary(self.hint_label)
            inputs.layout().addWidget(self.hint_label)
        lock.add(self)

    def _field_widget(self):
        return self.spin

    def set_maximum(self, max_value):
        self.spin.setMaximum(max_value)

    def set_hint(self, hint):
        self.hint_label.setText(hint)

    def set_enabled(self, enabled):
        self.spin.setEnabled(enabled)


class AutoNumberField(NumberField):
    """
    Number field that auto_var switches to an automatic value, e.g. the height kept from the
    aspect ratio or the original bitrate; auto_text is shown in place of the number then.
    With checkbox_text, a checkbox after the hint controls auto_var; without it, the owner sets auto_var.
    """

    def __init__(self, inputs, lock, variable, max_value, hint, auto_var, checkbox_text, auto_text,
                 allow_zero=False):
        self.auto_var = auto_var
        self.auto_text = QLineEdit(auto_text)
        self.auto_text.setEnabled(False)
        self.auto_text.setFixedWidth(NUMBER_FIELD_WIDTH)
        self.stack = QStackedWidget()
        super().__init__(inputs, lock, variable, max_value, hint, allow_zero)

        self.checkbox = None
        if checkbox_text is not None:
            self.checkbox = QCheckBox(checkbox_text)
            bind_checkbox(self.checkbox, auto_var)
            inputs.layout().addSpacing(15)
            inputs.layout().addWidget(self.checkbox)
        auto_var.changed.connect(self._update)
        self._update()

    def _field_widget(self):
        self.stack.addWidget(self.spin)
        self.stack.addWidget(self.auto_text)
        self.stack.setFixedWidth(NUMBER_FIELD_WIDTH)
        return self.stack

    def _update(self, *args):
        # The number is only used while the value isn't automatic
        self.stack.setCurrentWidget(self.auto_text if self.auto_var.get() else self.spin)

    def set_enabled(self, enabled):
        super().set_enabled(enabled)
        if self.checkbox is not None:
            self.checkbox.setEnabled(enabled)


def make_card(title):
    # Card of a group of settings: a frame with a bold title and a form of settings rows;
    # returns both
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 12)
    title_label = QLabel(title)
    font = QFont(title_label.font())
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 1.15)
    title_label.setFont(font)
    layout.addWidget(title_label)
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    form.setHorizontalSpacing(12)
    form.setVerticalSpacing(6)
    layout.addLayout(form)
    return card, form


def make_inputs(packed=True):
    # Row of inputs, e.g. a field, its hint and a checkbox; packed to the left,
    # or spread over the width for a field that should take all of it
    inputs = QWidget()
    layout = QHBoxLayout(inputs)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    if packed:
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return inputs


def add_setting_row(form, label, indent=False, packed=True):
    # Settings row: a label and the inputs next to it; returns both, e.g. to show or hide the row
    # with form.setRowVisible(inputs, …). Setting labels get the same width in all cards (see the main window)
    label_widget = QLabel(label)
    label_widget.setProperty("settingLabel", True)
    if indent:
        label_widget.setContentsMargins(20, 0, 0, 0)
    inputs = make_inputs(packed)
    form.addRow(label_widget, inputs)
    return label_widget, inputs

