import customtkinter as ctk

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
    SECTION_HOVER_COLOR,
    WATERMARK_MOTIONS,
)
from ui.fields import AutoNumberField, NumberField, add_setting_row
from ui.number_input import InvalidInput, parse_field, valid_number_or
from ui.settings import find_watermark_motion

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
            self.vars[field["name"]] = ctk.StringVar(value=valid_number_or(
                saved_value(field["name"]), str(field["default"]), field["max"], allow_zero="random" in field
            ))
            if "random" in field:
                self.vars[field["random"]] = ctk.BooleanVar(
                    value=bool(saved_value(field["random"], field["random_default"]))
                )

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
    """Rows of the fields of a motion's settings in the settings grid, from row on; can be shown or hidden."""

    def __init__(self, frame, row, lock, motion_settings, indent=False):
        self.widgets = []
        self.auto_fields = []
        for i, field in enumerate(motion_settings.fields):
            label, inputs = add_setting_row(frame, row + i, field["label"] + ":", indent)
            variable = motion_settings.vars[field["name"]]
            if "random" in field:
                self.auto_fields.append(AutoNumberField(
                    inputs, lock, variable, field["max"], field["hint"],
                    motion_settings.vars[field["random"]], "Random for each video", "random", allow_zero=True
                ))
            else:
                NumberField(inputs, lock, variable, field["max"], field["hint"])
            self.widgets += [label, inputs]
        self.row_count = len(motion_settings.fields)

    def show(self, shown=True):
        for widget in self.widgets:
            if shown:
                widget.grid()
            else:
                widget.grid_remove()

    def refresh(self):
        # The same settings are shown in two places, so a hidden random field may be out of date
        for field in self.auto_fields:
            field.update()


class CustomMotionSection:
    """
    Section of one motion in the custom motion: a header with a button that shows or hides
    its settings, whether the motion is used, and its number in turn; then its settings.
    The state is saved as e.g. "custom_bounce_use".
    """

    def __init__(self, frame, row, lock, motion_settings, number, saved, on_change, on_order_change):
        self.motion = motion_settings.motion
        self.prefix = f"custom_{MOTION_KEYS[self.motion]}_"
        self.vars = {
            "use": ctk.BooleanVar(value=bool(saved.get(self.prefix + "use", True))),
            "order": ctk.StringVar(value=str(saved.get(self.prefix + "order", number))),
            "expanded": ctk.BooleanVar(value=bool(saved.get(self.prefix + "expanded", True))),
        }

        self.header = ctk.CTkFrame(frame, fg_color="transparent")
        self.header.grid(row=row, column=0, columnspan=3, sticky="ew", padx=5, pady=(6, 2))
        # Not locked while rendering: it only shows or hides the settings
        self.toggle = ctk.CTkButton(
            self.header,
            fg_color="transparent",
            hover_color=SECTION_HOVER_COLOR,
            text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"],
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
            width=260,
            command=self._toggle
        )
        self.toggle.grid(row=0, column=0)
        self._on_change = on_change
        use_checkbox = ctk.CTkCheckBox(self.header, text="Use", variable=self.vars["use"], command=on_change)
        use_checkbox.grid(row=0, column=1, padx=(10, 0))
        ctk.CTkLabel(self.header, text="Number in turn:").grid(row=0, column=2, padx=(20, 5))
        self.order_menu = ctk.CTkOptionMenu(
            self.header,
            variable=self.vars["order"],
            values=[str(n) for n in range(1, len(MOTION_KEYS) + 1)],
            width=70,
            command=lambda number: on_order_change(self)
        )
        self.order_menu.grid(row=0, column=3)
        lock.add(use_checkbox, self.order_menu)

        self.rows = MotionRows(frame, row + 1, lock, motion_settings, indent=True)
        self.row_count = 1 + self.rows.row_count

    @property
    def used(self):
        return self.vars["use"].get()

    @property
    def order(self):
        return self.vars["order"].get()

    def _toggle(self):
        self.vars["expanded"].set(not self.vars["expanded"].get())
        self._on_change()

    def show(self, shown=True):
        expanded = self.vars["expanded"].get()
        self.toggle.configure(text=f"{'▼' if expanded else '▶'}  {self.motion}")
        if shown:
            self.header.grid()
        else:
            self.header.grid_remove()
        self.rows.show(shown and expanded)

    def update_order_menu(self, in_turn):
        # A number in turn is only needed when the motions go in turn and this one is used
        self.order_menu.configure(state="normal" if in_turn and self.used else "disabled")

    def variables(self):
        return list(self.vars.values())

    def settings(self):
        return {self.prefix + name: var.get() for name, var in self.vars.items()}


class MotionSection:
    """
    How the watermark moves: the motion menu, then the settings of the chosen motion right
    below it, or for the custom motion how the videos pick a motion and a section for each
    motion it mixes. Rows from row on in the settings grid; next_row is the first one after them.
    """

    def __init__(self, frame, row, lock, saved):
        self.lock = lock
        self.motion_var = ctk.StringVar(value=find_watermark_motion(saved.get("watermark_motion")))
        self.motion_settings = {motion: MotionSettings(motion, saved) for motion in MOTION_FIELDS}

        label, inputs = add_setting_row(frame, row, "Motion:")
        motion_menu = ctk.CTkOptionMenu(
            inputs, variable=self.motion_var, values=list(WATERMARK_MOTIONS), width=260,
            command=lambda motion: self.update()
        )
        motion_menu.grid(row=0, column=0)
        lock.add(motion_menu)
        row += 1

        # A motion on its own: its settings in the same rows for each motion
        self.motion_rows = {
            motion: MotionRows(frame, row, lock, settings) for motion, settings in self.motion_settings.items()
        }

        # Custom: how the videos pick a motion, then the sections of the motions it mixes
        self.custom_order_var = ctk.StringVar(value=saved.get("custom_motion_order", CUSTOM_ORDER_IN_TURN))
        if self.custom_order_var.get() not in CUSTOM_ORDERS:
            self.custom_order_var.set(CUSTOM_ORDER_IN_TURN)
        self.custom_order_label, inputs = add_setting_row(frame, row, "Motion order:")
        self.custom_order_inputs = inputs
        custom_order_menu = ctk.CTkOptionMenu(
            inputs, variable=self.custom_order_var, values=list(CUSTOM_ORDERS), width=260,
            command=lambda order: self.update()
        )
        custom_order_menu.grid(row=0, column=0)
        lock.add(custom_order_menu)
        row += 1
        self.custom_sections = []
        for number, motion in enumerate(MOTION_KEYS, start=1):
            section = CustomMotionSection(
                frame, row, lock, self.motion_settings[motion], number, saved, self.update, self._set_order
            )
            self.custom_sections.append(section)
            row += section.row_count
        self._check_orders()
        self.next_row = row

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

    def update(self):
        # Show only the settings of the chosen motion
        motion = self.motion_var.get()
        custom = motion not in self.motion_rows
        for rows_motion, rows in self.motion_rows.items():
            rows.show(rows_motion == motion)
        for widget in (self.custom_order_label, self.custom_order_inputs):
            if custom:
                widget.grid()
            else:
                widget.grid_remove()
        for section in self.custom_sections:
            section.show(custom)
        self._update_controls()

    def _update_controls(self):
        # Only while idle: rendering keeps everything locked
        if self.lock.locked:
            return
        for rows in [*self.motion_rows.values(), *(section.rows for section in self.custom_sections)]:
            rows.refresh()
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
