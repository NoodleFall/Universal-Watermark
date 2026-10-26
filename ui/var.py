from PySide6.QtCore import QObject, Signal


class Var(QObject):
    """
    Value of a setting, shared by its input and the code that reads it.
    changed is emitted with the new value only when the value actually changes.
    """

    changed = Signal(object)

    def __init__(self, value=""):
        super().__init__()
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        if value != self._value:
            self._value = value
            self.changed.emit(value)
