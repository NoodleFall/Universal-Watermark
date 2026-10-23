import customtkinter as ctk

from constants import DISABLED_TEXT_COLOR, NUMBER_INPUT_RE, NUMBER_STEP
from ui.number_input import format_number, parse_number


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
            elif isinstance(item, ctk.CTkEntry):
                set_entry_enabled(item, enabled)
            else:
                item.configure(state="normal" if enabled else "disabled")
        if enabled:
            for callback in self._unlock_callbacks:
                callback()


def set_entry_enabled(entry, enabled):
    # A disabled CTkEntry looks the same as an enabled one, so also gray out its text
    if not hasattr(entry, "default_text_color"):
        entry.default_text_color = entry.cget("text_color")
    entry.configure(
        state="normal" if enabled else "disabled",
        text_color=entry.default_text_color if enabled else DISABLED_TEXT_COLOR
    )


class NumberField:
    """
    Entry for a number up to max_value (a number, or a function returning it) with ▲/▼ buttons,
    placed in the grid of parent, with an optional hint after it. The Up/Down keys step the
    number too, and so does the mouse wheel while the field has the cursor.
    The number is above zero, or zero too with allow_zero.
    """

    def __init__(self, parent, lock, variable, max_value, hint=None, allow_zero=False):
        self.variable = variable
        self._max_value = max_value
        self.allow_zero = allow_zero

        self.entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            width=70,
            validate="key",
            validatecommand=(parent.register(self._validate), "%P")
        )
        self.entry.grid(row=0, column=0)

        arrows = ctk.CTkFrame(parent, fg_color="transparent")
        arrows.grid(row=0, column=1, padx=(3, 0))
        up = ctk.CTkButton(arrows, text="▲", width=22, height=13, font=("", 8), command=lambda: self.step(1))
        up.grid(row=0, column=0, pady=(0, 1))
        down = ctk.CTkButton(arrows, text="▼", width=22, height=13, font=("", 8), command=lambda: self.step(-1))
        down.grid(row=1, column=0)
        self.arrows = (up, down)

        self.entry.bind("<Up>", lambda e: self.step(1))
        self.entry.bind("<Down>", lambda e: self.step(-1))
        self.entry.bind("<MouseWheel>", lambda e: self._wheel(1 if e.delta > 0 else -1))
        self.entry.bind("<Button-4>", lambda e: self._wheel(1))
        self.entry.bind("<Button-5>", lambda e: self._wheel(-1))

        if hint is not None:
            ctk.CTkLabel(parent, text=hint).grid(row=0, column=2, padx=(5, 0))
        lock.add(self)

    @property
    def max_value(self):
        return self._max_value() if callable(self._max_value) else self._max_value

    def _validate(self, value):
        if not NUMBER_INPUT_RE.fullmatch(value):
            return False
        number = parse_number(value)
        if number is not None and number > self.max_value:
            # Too large: reset the field to the maximum. Changing the variable inside
            # the validation would turn validation off, so do it right after
            self.entry.after_idle(self.variable.set, format_number(self.max_value))
            return False
        return True

    def _wheel(self, direction):
        # The mouse wheel changes the value only while the field has the cursor,
        # otherwise it scrolls the settings, so scrolling past a field doesn't change it.
        # The CTkEntry frame holds the Tk entry that gets the focus
        focused = self.entry.focus_get()
        if focused is None or not str(focused).startswith(str(self.entry) + "."):
            return None
        self.step(direction)
        # Don't scroll the settings as well
        return "break"

    def step(self, direction):
        if self.entry.cget("state") == "disabled":
            return
        current = parse_number(self.variable.get()) or 0
        new = round(current + direction * NUMBER_STEP, 2)
        if self.allow_zero:
            # Stay within [0, max_value]: going below zero stops at zero
            new = max(new, 0)
        elif new <= 0:
            # Stay within (0, max_value]: going below zero keeps the current value
            return
        self.variable.set(format_number(min(new, self.max_value)))

    def set_enabled(self, enabled):
        set_entry_enabled(self.entry, enabled)
        for arrow in self.arrows:
            arrow.configure(state="normal" if enabled else "disabled")


class AutoNumberField(NumberField):
    """
    Number field that auto_var switches to an automatic value, e.g. the height kept from the
    aspect ratio or the original bitrate. With checkbox_text, a checkbox controls auto_var;
    without it, the owner sets auto_var and calls update().
    """

    def __init__(self, parent, lock, variable, max_value, hint, auto_var, checkbox_text, auto_text,
                 allow_zero=False):
        super().__init__(parent, lock, variable, max_value, hint, allow_zero)
        self.auto_var = auto_var
        # Shown in the field instead of the number while the checkbox is on
        self.auto_text_var = ctk.StringVar(value=auto_text)
        self.text_color = self.entry.cget("text_color")
        self.checkbox = None
        if checkbox_text is not None:
            self.checkbox = ctk.CTkCheckBox(parent, text=checkbox_text, variable=auto_var, command=self.update)
            self.checkbox.grid(row=0, column=3, padx=(20, 0))
        self.update()

    def update(self):
        # The custom value is only used when the checkbox is off.
        # A disabled CTkEntry looks the same as an enabled one,
        # so also show the automatic value in gray instead of the custom one.
        # Switching the variable runs the input validation on that text, and Tk turns
        # validation off for good when it fails, so pause it during the switch
        is_auto = self.auto_var.get()
        self.entry.configure(validate="none")
        if is_auto:
            self.entry.configure(state="disabled", textvariable=self.auto_text_var, text_color=DISABLED_TEXT_COLOR)
        else:
            self.entry.configure(state="normal", textvariable=self.variable, text_color=self.text_color)
        self.entry.configure(validate="key")
        for arrow in self.arrows:
            arrow.configure(state="disabled" if is_auto else "normal")

    def set_enabled(self, enabled):
        # Unlocked, the field also depends on its checkbox
        if self.checkbox is not None:
            self.checkbox.configure(state="normal" if enabled else "disabled")
        if enabled:
            self.update()
        else:
            self.entry.configure(state="disabled", text_color=DISABLED_TEXT_COLOR)
            for arrow in self.arrows:
                arrow.configure(state="disabled")


def add_setting_row(frame, row, label, indent=False):
    # Label in the first column of the settings grid and a frame for the inputs next to it;
    # returns both, e.g. to show or hide the row
    label_widget = ctk.CTkLabel(frame, text=label)
    label_widget.grid(row=row, column=0, sticky="w", padx=(30 if indent else 10, 10), pady=2)
    return label_widget, add_inputs_frame(frame, row)


def add_inputs_frame(frame, row):
    # Frame for the inputs of a row of the settings grid, next to its label
    inputs = ctk.CTkFrame(frame, fg_color="transparent")
    inputs.grid(row=row, column=1, columnspan=2, sticky="w", padx=5, pady=2)
    return inputs
