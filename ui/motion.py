from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QToolButton

from constants import (
    CUSTOM_ORDER_IN_TURN,
    CUSTOM_ORDER_RANDOM,
    CUSTOM_ORDERS,
    DEFAULT_BOUNCE_SPEED_PERCENT,
    DEFAULT_POSITION_CHANGE_SECONDS,
    DEFAULT_TRAVEL_TIME_SECONDS,
    MAX_BOUNCE_SPEED_PERCENT,
    MAX_PERCENT,
    MAX_POSITION_CHANGE_SECONDS,
    MAX_TRAVEL_TIME_SECONDS,
    MOTION_BOUNCE,
    MOTION_KEYS,
    MOTION_TOP_TO_BOTTOM,
    WATERMARK_MOTIONS,
)
from ui.fields import (
    MENU_MIN_WIDTH,
    AutoNumberField,
    NumberField,
    add_setting_row,
    bind_checkbox,
    bind_combo,
    make_card,
    make_inputs,
)
from ui.number_input import InvalidInput, parse_field, valid_number_or
from ui.settings import find_watermark_motion
from ui.var import Var

# Fields of the settings of each motion, in their order on screen. name: setting of add_watermark();
# random: name of the checkbox that picks a random value instead (such fields accept zero),
# random_default: whether it starts checked
MOTION_FIELDS = {
    MOTION_TOP_TO_BOTTOM: (
        {"name": "travel_time_seconds", "label": "Travel time", "max": MAX_TRAVEL_TIME_SECONDS,
         "default": DEFAULT_TRAVEL_TIME_SECONDS, "hint": f"seconds from top to bottom (max: {MAX_TRAVEL_TIME_SECONDS})"},
        # Vertical position at the start of each video, as a percentage of the travel
        # from the top, so it means the same for any resolution
        {"name": "start_position_percent", "label": "Start position", "max": MAX_PERCENT, "default": 0,
         "hint": f"% from the top (0 = top, {MAX_PERCENT} = bottom)",
         "random": "random_start_position", "random_default": False},
        {"name": "position_change_seconds", "label": "Position change", "max": MAX_POSITION_CHANGE_SECONDS,
         "default": DEFAULT_POSITION_CHANGE_SECONDS,
         "hint": f"seconds between horizontal jumps (max: {MAX_POSITION_CHANGE_SECONDS})"},
    ),
    MOTION_BOUNCE: (
        # Speed as a percentage of the video height per second, the same in pixels
        # on both axes, so it looks the same for any resolution
        {"name": "bounce_speed_percent", "label": "Speed", "max": MAX_BOUNCE_SPEED_PERCENT,
         "default": DEFAULT_BOUNCE_SPEED_PERCENT,
         "hint": f"% of video height per second (max: {MAX_BOUNCE_SPEED_PERCENT})"},
        {"name": "start_position_percent", "label": "Vertical start", "max": MAX_PERCENT, "default": 0,
         "hint": f"% from the top (0 = top, {MAX_PERCENT} = bottom)",
         "random": "random_start_position", "random_default": False},
        # Random by default: the bouncing watermark always started at a random horizontal position before
        {"name": "horizontal_start_percent", "label": "Horizontal start", "max": MAX_PERCENT, "default": 0,
         "hint": f"% from the left (0 = left, {MAX_PERCENT} = right)",
         "random": "random_horizontal_start", "random_default": True},
    ),
}


class MotionSettings:
    """
    Settings of one motion: {field name: variable}, the same whether the motion is chosen
    on its own or mixed in the custom motion, so a change in one place shows in the other.
    Saved under the motion's name, e.g. "bounce_bounce_speed_percent".
    """

    def __init__(self, motion, saved):
        self.motion = motion
        self.prefix = MOTION_KEYS[motion] + "_"
        self.fields = MOTION_FIELDS[motion]

        def saved_value(name, default=None):
            # Settings from before they were saved under the motion's name have the field name alone
            return saved.get(self.prefix + name, saved.get(name, default))

        self.vars = {}
        for field in self.fields:
            self.vars[field["name"]] = Var(valid_number_or(
                saved_value(field["name"]), str(field["default"]), field["max"], allow_zero="random" in field
            ))
            if "random" in field:
                self.vars[field["random"]] = Var(bool(saved_value(field["random"], field["random_default"])))

    def variables(self):
        return list(self.vars.values())

    def settings(self):
        return {self.prefix + name: var.get() for name, var in self.vars.items()}

    def parse(self, name_prefix=""):
        # Returns the add_watermark() settings of the motion, or raises InvalidInput;
        # a field with its random checkbox on gives None, a random value for each video
        result = {"motion": self.motion}
        for field in self.fields:
            if "random" in field and self.vars[field["random"]].get():
                result[field["name"]] = None
            else:
                result[field["name"]] = parse_field(
                    self.vars[field["name"]].get(), name_prefix + field["label"], field["max"],
                    allow_zero="random" in field
                )
        return result


class MotionRows:
    """Rows of the fields of a motion's settings, added to the end of form; can be shown or hidden."""

    def __init__(self, form, lock, motion_settings, indent=False):
        self.form = form
        self.rows = []
        for field in motion_settings.fields:
            _, inputs = add_setting_row(form, field["label"] + ":", indent)
            variable = motion_settings.vars[field["name"]]
            if "random" in field:
                AutoNumberField(
                    inputs, lock, variable, field["max"], field["hint"],
                    motion_settings.vars[field["random"]], "Random for each video", "random", allow_zero=True
                )
            else:
                NumberField(inputs, lock, variable, field["max"], field["hint"])
            self.rows.append(inputs)

    def show(self, shown=True):
        for inputs in self.rows:
            self.form.setRowVisible(inputs, shown)


class CustomMotionSection:
    """
    Section of one motion in the custom motion: a header with a button that shows or hides
    its settings, whether the motion is used, and its number in turn; then its settings.
    The state is saved as e.g. "custom_bounce_use".
    """

    def __init__(self, form, lock, motion_settings, number, saved, on_change, on_order_change):
        self.form = form
        self.motion = motion_settings.motion
        self.prefix = f"custom_{MOTION_KEYS[self.motion]}_"
        self.vars = {
            "use": Var(bool(saved.get(self.prefix + "use", True))),
            "order": Var(str(saved.get(self.prefix + "order", number))),
            "expanded": Var(bool(saved.get(self.prefix + "expanded", True))),
        }

        self.header = make_inputs()
        header = self.header.layout()
        header.setContentsMargins(0, 6, 0, 0)
        # Not locked while rendering: it only shows or hides the settings
        self.toggle = QToolButton()
        self.toggle.setObjectName("sectionToggle")
        self.toggle.setText(self.motion)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setAutoRaise(True)
        self.toggle.setMinimumWidth(MENU_MIN_WIDTH)
        font = self.toggle.font()
        font.setBold(True)
        self.toggle.setFont(font)
        self.toggle.clicked.connect(self._toggle)
        header.addWidget(self.toggle)

        use_checkbox = QCheckBox("Use")
        bind_checkbox(use_checkbox, self.vars["use"])
        header.addSpacing(10)
        header.addWidget(use_checkbox)
        header.addSpacing(20)
        header.addWidget(QLabel("Number in turn:"))
        self.order_menu = QComboBox()
        self.order_menu.addItems([str(n) for n in range(1, len(MOTION_KEYS) + 1)])
        bind_combo(self.order_menu, self.vars["order"])
        # Only a number the user picks moves the other sections' numbers, not one set from the code
        self.order_menu.activated.connect(lambda index: on_order_change(self))
        header.addWidget(self.order_menu)
        lock.add(use_checkbox, self.order_menu)
        form.addRow(self.header)

        self.vars["use"].changed.connect(on_change)
        self.vars["expanded"].changed.connect(on_change)
        self.rows = MotionRows(form, lock, motion_settings, indent=True)

    @property
    def used(self):
        return self.vars["use"].get()

    @property
    def order(self):
        return self.vars["order"].get()

    def _toggle(self):
        self.vars["expanded"].set(not self.vars["expanded"].get())

    def show(self, shown=True):
        expanded = self.vars["expanded"].get()
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.form.setRowVisible(self.header, shown)
        self.rows.show(shown and expanded)

    def update_order_menu(self, in_turn):
        # A number in turn is only needed when the motions go in turn and this one is used
        self.order_menu.setEnabled(in_turn and self.used)

    def variables(self):
        return list(self.vars.values())

    def settings(self):
        return {self.prefix + name: var.get() for name, var in self.vars.items()}


class MotionSection:
    """
    How the watermark moves: the motion menu, then the settings of the chosen motion right
    below it, or for the custom motion how the videos pick a motion and a section for each
    motion it mixes. Shown in its own card.
    """

    def __init__(self, lock, saved):
        self.lock = lock
        self.motion_var = Var(find_watermark_motion(saved.get("watermark_motion")))
        self.motion_settings = {motion: MotionSettings(motion, saved) for motion in MOTION_FIELDS}
        self.card, self.form = make_card("Motion")

        _, inputs = add_setting_row(self.form, "Motion:")
        motion_menu = QComboBox()
        motion_menu.addItems(list(WATERMARK_MOTIONS))
        motion_menu.setMinimumWidth(MENU_MIN_WIDTH)
        bind_combo(motion_menu, self.motion_var)
        inputs.layout().addWidget(motion_menu)
        lock.add(motion_menu)

        # A motion on its own: its settings right below the menu
        self.motion_rows = {
            motion: MotionRows(self.form, lock, settings) for motion, settings in self.motion_settings.items()
        }

        # Custom: how the videos pick a motion, then the sections of the motions it mixes
        self.custom_order_var = Var(saved.get("custom_motion_order", CUSTOM_ORDER_IN_TURN))
        if self.custom_order_var.get() not in CUSTOM_ORDERS:
            self.custom_order_var.set(CUSTOM_ORDER_IN_TURN)
        _, self.custom_order_inputs = add_setting_row(self.form, "Motion order:")
        custom_order_menu = QComboBox()
        custom_order_menu.addItems(list(CUSTOM_ORDERS))
        custom_order_menu.setMinimumWidth(MENU_MIN_WIDTH)
        bind_combo(custom_order_menu, self.custom_order_var)
        self.custom_order_inputs.layout().addWidget(custom_order_menu)
        lock.add(custom_order_menu)
        self.custom_sections = [
            CustomMotionSection(
                self.form, lock, self.motion_settings[motion], number, saved, self.update, self._set_order
            )
            for number, motion in enumerate(MOTION_KEYS, start=1)
        ]
        self._check_orders()

        self.motion_var.changed.connect(self.update)
        self.custom_order_var.changed.connect(self.update)
        # After rendering, the numbers in turn depend on the order and the "Use" checkboxes again
        lock.on_unlock(self._update_controls)
        self.update()

    def _check_orders(self):
        # Numbers in turn must be 1, 2, … without repeats; otherwise use the default order
        numbers = [str(n) for n in range(1, len(self.custom_sections) + 1)]
        if sorted(section.order for section in self.custom_sections) != numbers:
            for section, number in zip(self.custom_sections, numbers):
                section.vars["order"].set(number)

    def _set_order(self, changed):
        # The section that had the chosen number takes the number left free, so the numbers don't repeat
        free = {str(n) for n in range(1, len(self.custom_sections) + 1)}
        free -= {section.order for section in self.custom_sections}
        for section in self.custom_sections:
            if section is not changed and section.order == changed.order and free:
                section.vars["order"].set(free.pop())

    def update(self, *args):
        # Show only the settings of the chosen motion
        motion = self.motion_var.get()
        custom = motion not in self.motion_rows
        for rows_motion, rows in self.motion_rows.items():
            rows.show(rows_motion == motion)
        self.form.setRowVisible(self.custom_order_inputs, custom)
        for section in self.custom_sections:
            section.show(custom)
        self._update_controls()

    def _update_controls(self):
        # Only while idle: rendering keeps everything locked
        if self.lock.locked:
            return
        in_turn = self.custom_order_var.get() == CUSTOM_ORDER_IN_TURN
        for section in self.custom_sections:
            section.update_order_menu(in_turn)

    def variables(self):
        # Each variable once, so a change saves the settings once
        variables = [self.motion_var, self.custom_order_var]
        for settings in self.motion_settings.values():
            variables += settings.variables()
        for section in self.custom_sections:
            variables += section.variables()
        return variables

    def settings(self):
        result = {"watermark_motion": self.motion_var.get(), "custom_motion_order": self.custom_order_var.get()}
        for settings in self.motion_settings.values():
            result.update(settings.settings())
        for section in self.custom_sections:
            result.update(section.settings())
        return result

    def parse(self):
        # Returns the motions for main() and whether each video takes a random one, or raises InvalidInput.
        # The hidden settings of the other motions aren't used
        motion = self.motion_var.get()
        if motion in self.motion_settings:
            return [self.motion_settings[motion].parse()], False
        # Custom: the used motions in turn by their numbers, or each video takes a random one
        used = sorted((s for s in self.custom_sections if s.used), key=lambda s: int(s.order))
        if not used:
            raise InvalidInput("Custom motion: turn on \"Use\" for at least one motion.")
        motions = [self.motion_settings[s.motion].parse(f"{s.motion}: ") for s in used]
        return motions, self.custom_order_var.get() == CUSTOM_ORDER_RANDOM
