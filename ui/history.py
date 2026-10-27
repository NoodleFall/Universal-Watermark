import time

from PySide6.QtCore import QTimer

# Steps kept for undoing
MAX_STEPS = 200
# Changes of the same settings closer than this make one step, e.g. a number typed digit by digit
MERGE_SECONDS = 1.5


class Step:
    """
    One action that can be undone: undo() and redo() apply it. Changes of settings keep {var: [old value, new value]} in values.
    """

    def __init__(self, undo=None, redo=None, values=None):
        self._undo = undo
        self._redo = redo
        self.values = values
        self.time = time.monotonic()

    def undo(self):
        if self.values is None:
            self._undo()
        else:
            for var, (old, new) in self.values.items():
                var.set(old)

    def redo(self):
        if self.values is None:
            self._redo()
        else:
            for var, (old, new) in self.values.items():
                var.set(new)


class History:
    """
    Undo and redo of one page of the window: of its settings and its actions.
    track() records the changes of a variable; the changes made in one pass of the event loop
    make one step, so an action that changes several settings is undone at once. push() adds an
    action, e.g. adding videos to the list.
    """

    def __init__(self):
        self.undo_steps = []
        self.redo_steps = []
        # Last value of each tracked variable, the old value of its next change
        self._values = {}
        # Changes of this pass of the event loop: {var: [old value, new value]}
        self._pending = {}
        # The settings step that the next changes of the same settings join, or None
        self._mergeable = None
        # While undoing or redoing, the changes it makes aren't recorded
        self._applying = False

    def track(self, var):
        self._values[var] = var.get()
        # The current value, not the emitted one: a slot that ran before may have changed it again
        var.changed.connect(lambda value: self._on_changed(var))

    def _on_changed(self, var):
        new = var.get()
        old = self._values[var]
        self._values[var] = new
        if self._applying:
            return
        if not self._pending:
            QTimer.singleShot(0, self._flush)
        self._pending.setdefault(var, [old, new])[1] = new

    def _flush(self):
        # Make a step of the pending changes, or add them to the last step of the same settings
        pending = {var: values for var, values in self._pending.items() if values[0] != values[1]}
        self._pending = {}
        if not pending:
            return
        step = self._mergeable
        if (step is not None and self.undo_steps and self.undo_steps[-1] is step
                and step.values.keys() == pending.keys() and time.monotonic() - step.time < MERGE_SECONDS):
            for var, (old, new) in pending.items():
                step.values[var][1] = new
            step.time = time.monotonic()
            if all(old == new for old, new in step.values.values()):
                # Back where the step started, e.g. a checkbox the program turned off right away
                self.undo_steps.pop()
                self._mergeable = None
            return
        step = Step(values=pending)
        self._add(step)
        self._mergeable = step

    def push(self, undo, redo):
        # Record an action that is already done: undo() reverts it, redo() does it again
        self._flush()
        self._add(Step(undo, redo))
        self._mergeable = None

    def _add(self, step):
        self.undo_steps.append(step)
        del self.undo_steps[:-MAX_STEPS]
        self.redo_steps.clear()

    def can_undo(self):
        self._flush()
        return bool(self.undo_steps)

    def can_redo(self):
        self._flush()
        return bool(self.redo_steps)

    def undo(self):
        if self.can_undo():
            step = self.undo_steps.pop()
            self._apply(step, step.undo)
            self.redo_steps.append(step)

    def redo(self):
        if self.can_redo():
            step = self.redo_steps.pop()
            self._apply(step, step.redo)
            self.undo_steps.append(step)

    def _apply(self, step, action):
        self._mergeable = None
        self._applying = True
        try:
            action()
        finally:
            self._applying = False
