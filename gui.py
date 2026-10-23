import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from constants import (
    APP_NAME,
    CUSTOM_MOTION_KEYS,
    CUSTOM_ORDERS,
    CUSTOM_ORDER_IN_TURN,
    CUSTOM_ORDER_RANDOM,
    DEFAULT_BOUNCE_SPEED_PERCENT,
    DEFAULT_POSITION_CHANGE_SECONDS,
    DEFAULT_TRAVEL_TIME_SECONDS,
    DISABLED_TEXT_COLOR,
    LOUDNESS_PRESETS,
    MAX_BITRATE_KBPS,
    MAX_BOUNCE_SPEED_PERCENT,
    MAX_CRF,
    MAX_GPU_QP,
    MAX_PERCENT,
    MAX_POSITION_CHANGE_SECONDS,
    MAX_TRAVEL_TIME_SECONDS,
    MAX_WINDOW_SCREEN_SHARE,
    MIN_SETTINGS_HEIGHT,
    MOTION_BOUNCE,
    MOTION_TOP_TO_BOTTOM,
    NUMBER_INPUT_RE,
    NUMBER_STEP,
    QUALITY_CRF,
    QUALITY_CUSTOM_BITRATE,
    QUALITY_GPU_QP,
    QUALITY_ORIGINAL_BITRATE,
    RECOMMENDED_CRF,
    SECTION_HOVER_COLOR,
    VIDEO_CODECS,
    VIDEO_QUALITY_MODES,
    VIDEO_STAGE_PLACEHOLDER,
    WATERMARK_MOTIONS,
)
from functions.encoders import find_cpu_encoder, find_gpu_encoder, get_gpu_qp_scale
from functions.render_control import RenderCancelled, RenderControl
from main import main
from number_input import format_number, is_number_input, parse_number, valid_number_or
from settings import (
    find_codec,
    find_loudness_preset,
    find_video_quality_mode,
    find_watermark_motion,
    load_settings,
    save_settings,
)


# Fields of the settings of each motion, in their order on screen. name: setting of add_watermark(),
# also its name in the settings file; random: name of the checkbox that picks a random value instead
# (such fields accept zero), random_default: whether it starts checked
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


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.resizable(True, True)

        # Restore the settings from the previous run, falling back to defaults
        settings = load_settings()
        self.raw_videos_var = ctk.StringVar(value=settings.get("raw_videos_path", "raw_videos"))
        self.output_folder_var = ctk.StringVar(value=settings.get("output_folder_path", "watermarked_videos"))
        self.watermark_image_var = ctk.StringVar(value=settings.get("watermark_image_path", "watermark.png"))
        self.width_var = ctk.StringVar(value=valid_number_or(settings.get("width_percent"), "50", MAX_PERCENT))
        self.height_var = ctk.StringVar(value=valid_number_or(settings.get("height_percent"), "20", MAX_PERCENT))
        self.keep_ratio_var = ctk.BooleanVar(value=bool(settings.get("keep_aspect_ratio", True)))
        self.opacity_var = ctk.StringVar(value=valid_number_or(settings.get("opacity_percent"), "33", MAX_PERCENT))
        self.motion_var = ctk.StringVar(value=find_watermark_motion(settings.get("watermark_motion")))
        # Settings of each motion when it's chosen on its own: {motion: {field name: variable}}.
        # Both motions share the vertical start position
        self.motion_vars = {motion: self._load_motion_vars(settings, motion, "") for motion in MOTION_FIELDS}
        for name in ("start_position_percent", "random_start_position"):
            self.motion_vars[MOTION_BOUNCE][name] = self.motion_vars[MOTION_TOP_TO_BOTTOM][name]
        # The custom motion has its own settings of each motion it mixes, saved with a prefix,
        # and whether the motion is used, its number in turn and whether its settings are shown
        self.custom_motion_vars = {}
        self.custom_motion_state = {}
        for i, (motion, key) in enumerate(CUSTOM_MOTION_KEYS.items()):
            prefix = f"custom_{key}_"
            self.custom_motion_vars[motion] = self._load_motion_vars(settings, motion, prefix)
            self.custom_motion_state[motion] = {
                "use": ctk.BooleanVar(value=bool(settings.get(prefix + "use", True))),
                "order": ctk.StringVar(value=str(settings.get(prefix + "order", i + 1))),
                "expanded": ctk.BooleanVar(value=bool(settings.get(prefix + "expanded", True))),
            }
        # Numbers in turn must be 1, 2, … without repeats; otherwise use the default order
        orders = sorted(state["order"].get() for state in self.custom_motion_state.values())
        if orders != [str(n) for n in range(1, len(orders) + 1)]:
            for i, state in enumerate(self.custom_motion_state.values()):
                state["order"].set(str(i + 1))
        self.custom_order_var = ctk.StringVar(value=settings.get("custom_motion_order", CUSTOM_ORDER_IN_TURN))
        if self.custom_order_var.get() not in CUSTOM_ORDERS:
            self.custom_order_var.set(CUSTOM_ORDER_IN_TURN)
        self.video_quality_var = ctk.StringVar(value=find_video_quality_mode(settings))
        self.crf_var = ctk.StringVar(value=valid_number_or(settings.get("crf"), str(RECOMMENDED_CRF), MAX_CRF))
        self.bitrate_var = ctk.StringVar(value=valid_number_or(settings.get("bitrate_kbps"), "8000", MAX_BITRATE_KBPS))
        # QP of the video card encoder on its own scale, and the encoder it was set for
        self.gpu_qp_var = ctk.StringVar(value=valid_number_or(settings.get("gpu_qp"), "", MAX_GPU_QP))
        self.gpu_qp_encoder_var = ctk.StringVar(value=settings.get("gpu_qp_encoder", ""))
        # Video card encoder used for the chosen codec, or None; set by _check_gpu()
        self.gpu_encoder = None
        self.gpu_qp_max = MAX_GPU_QP
        # Shows "original" in the bitrate field; set from the video quality mode
        self.original_bitrate_var = ctk.BooleanVar()
        self.codec_var = ctk.StringVar(value=find_codec(settings.get("video_codec")))
        self.use_gpu_var = ctk.BooleanVar(value=bool(settings.get("use_gpu", False)))
        self.normalize_audio_var = ctk.BooleanVar(value=bool(settings.get("normalize_audio", False)))
        self.loudness_preset_var = ctk.StringVar(value=find_loudness_preset(settings.get("loudness_preset")))

        # Save the settings whenever any of them changes. Shared motion variables are listed
        # once (by id, as Tk variables can't be hashed), so a change saves the settings once
        motion_vars = {
            id(var): var
            for groups in (self.motion_vars, self.custom_motion_vars, self.custom_motion_state)
            for group in groups.values()
            for var in group.values()
        }.values()
        for var in (self.raw_videos_var, self.output_folder_var, self.watermark_image_var,
                    self.width_var, self.height_var, self.keep_ratio_var, self.opacity_var,
                    self.motion_var, self.custom_order_var, *motion_vars,
                    self.video_quality_var, self.crf_var, self.bitrate_var,
                    self.gpu_qp_var, self.gpu_qp_encoder_var,
                    self.codec_var, self.use_gpu_var, self.normalize_audio_var, self.loudness_preset_var):
            var.trace_add("write", self._save_settings)

        # Pause/stop control of the current rendering, None when idle
        self.control = None
        self.paused = False

        self.status_var = ctk.StringVar(value="Ready")
        self.video_percent_var = ctk.StringVar(value="0%")

        # Settings scroll when the window is too short for them; the buttons and the progress below stay in view
        frame = ctk.CTkScrollableFrame(root)
        frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        # Inputs that are locked while rendering
        self.input_entries = []
        self.input_buttons = []
        # Fields that can be switched to an automatic value by a checkbox
        self.auto_fields = []

        self._add_path_row(frame, 0, "Raw videos folder:", self.raw_videos_var, self._browse_raw_videos)
        self._add_path_row(frame, 1, "Output folder:", self.output_folder_var, self._browse_output_folder)
        self._add_path_row(frame, 2, "Watermark image:", self.watermark_image_var, self._browse_watermark)

        # Watermark width as a percentage of the video width
        ctk.CTkLabel(frame, text="Watermark width:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        width_row = ctk.CTkFrame(frame, fg_color="transparent")
        width_row.grid(row=3, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(width_row, self.width_var, MAX_PERCENT)
        ctk.CTkLabel(width_row, text=f"% of video width (max: {MAX_PERCENT})").grid(row=0, column=2, padx=(5, 0))

        # Watermark height: derived from the width, or a custom percentage of the video height
        ctk.CTkLabel(frame, text="Watermark height:").grid(row=4, column=0, sticky="w", padx=10, pady=2)
        height_row = ctk.CTkFrame(frame, fg_color="transparent")
        height_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_auto_field(
            height_row, self.height_var, MAX_PERCENT, f"% of video height (max: {MAX_PERCENT})",
            self.keep_ratio_var, "Keep aspect ratio", "auto"
        )

        # Watermark opacity: 100% is fully opaque
        ctk.CTkLabel(frame, text="Watermark opacity:").grid(row=5, column=0, sticky="w", padx=10, pady=2)
        opacity_row = ctk.CTkFrame(frame, fg_color="transparent")
        opacity_row.grid(row=5, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(opacity_row, self.opacity_var, MAX_PERCENT)
        ctk.CTkLabel(opacity_row, text=f"% (max: {MAX_PERCENT})").grid(row=0, column=2, padx=(5, 0))

        # How the watermark moves: top to bottom with horizontal jumps, or bouncing off the edges
        ctk.CTkLabel(frame, text="Motion:").grid(row=6, column=0, sticky="w", padx=10, pady=2)
        motion_menu = ctk.CTkOptionMenu(
            frame,
            variable=self.motion_var,
            values=list(WATERMARK_MOTIONS),
            width=260,
            command=lambda motion: self._update_motion_fields()
        )
        motion_menu.grid(row=6, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.input_buttons.append(motion_menu)

        # Rows of the motion settings; _update_motion_fields() shows those of the chosen motion.
        # A motion chosen on its own: its settings right below the menu, in the same rows for each motion
        self.motion_widgets = {
            motion: self._add_motion_rows(frame, 7, motion, self.motion_vars[motion]) for motion in MOTION_FIELDS
        }

        # Custom: how the videos pick a motion, then a collapsible section for each motion
        # with its header (name, whether it's used, its number in turn) and its own settings
        self.custom_order_label = ctk.CTkLabel(frame, text="Motion order:")
        self.custom_order_label.grid(row=7, column=0, sticky="w", padx=10, pady=2)
        self.custom_order_menu = ctk.CTkOptionMenu(
            frame,
            variable=self.custom_order_var,
            values=list(CUSTOM_ORDERS),
            width=260,
            command=lambda order: self._update_motion_fields()
        )
        self.custom_order_menu.grid(row=7, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.input_buttons.append(self.custom_order_menu)
        self.custom_sections = {}
        row = 8
        for motion in CUSTOM_MOTION_KEYS:
            header = self._add_custom_motion_header(frame, row, motion)
            rows = self._add_motion_rows(frame, row + 1, motion, self.custom_motion_vars[motion], indent=True)
            self.custom_sections[motion] = {"header": header, "rows": rows}
            row += 1 + len(MOTION_FIELDS[motion])
        self._update_motion_fields()

        # Video codec: H.264, HEVC or AV1
        ctk.CTkLabel(frame, text="Video codec:").grid(row=20, column=0, sticky="w", padx=10, pady=2)
        codec_row = ctk.CTkFrame(frame, fg_color="transparent")
        codec_row.grid(row=20, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        codec_menu = ctk.CTkOptionMenu(
            codec_row,
            variable=self.codec_var,
            values=list(VIDEO_CODECS),
            width=260,
            command=lambda codec: self._check_gpu()
        )
        codec_menu.grid(row=0, column=0)
        self.input_buttons.append(codec_menu)

        # Encode with the video card: faster, but usually bigger files for the same quality
        gpu_checkbox = ctk.CTkCheckBox(
            codec_row,
            text="Use GPU (faster, bigger files)",
            variable=self.use_gpu_var,
            command=self._check_gpu
        )
        gpu_checkbox.grid(row=0, column=1, padx=(20, 0))
        self.input_buttons.append(gpu_checkbox)

        # Video quality: constant quality (CRF), the bitrate of each original video, or a custom bitrate
        ctk.CTkLabel(frame, text="Video quality:").grid(row=21, column=0, sticky="w", padx=10, pady=2)
        # The menu shows display names: the constant quality mode reads "(QP)" while a video
        # card encodes; video_quality_var keeps the mode itself, as saved in the settings
        self.quality_menu = ctk.CTkOptionMenu(
            frame,
            values=list(VIDEO_QUALITY_MODES),
            width=220,
            command=self._select_quality_mode
        )
        self.quality_menu.grid(row=21, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.input_buttons.append(self.quality_menu)

        # Value of the chosen quality mode: the CRF or the bitrate field, in the same place
        self.quality_value_label_var = ctk.StringVar()
        ctk.CTkLabel(frame, textvariable=self.quality_value_label_var).grid(row=22, column=0, sticky="w", padx=10, pady=2)
        self.crf_row = ctk.CTkFrame(frame, fg_color="transparent")
        self.crf_row.grid(row=22, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(self.crf_row, self.crf_var, MAX_CRF)
        ctk.CTkLabel(
            self.crf_row,
            text=f"lower = better quality, {RECOMMENDED_CRF} recommended (max: {MAX_CRF})"
        ).grid(row=0, column=2, padx=(5, 0))
        # QP of the video card, shown instead of the CRF when it encodes the video;
        # its highest value depends on the encoder
        self.gpu_qp_row = ctk.CTkFrame(frame, fg_color="transparent")
        self.gpu_qp_row.grid(row=22, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(self.gpu_qp_row, self.gpu_qp_var, lambda: self.gpu_qp_max)
        self.gpu_qp_hint_var = ctk.StringVar()
        ctk.CTkLabel(self.gpu_qp_row, textvariable=self.gpu_qp_hint_var).grid(row=0, column=2, padx=(5, 0))
        self.bitrate_row = ctk.CTkFrame(frame, fg_color="transparent")
        self.bitrate_row.grid(row=22, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.bitrate_field = self._add_auto_field(
            self.bitrate_row, self.bitrate_var, MAX_BITRATE_KBPS, f"kb/s (max: {MAX_BITRATE_KBPS})",
            self.original_bitrate_var, None, "original"
        )
        self._update_quality_fields()

        # Audio normalization: off, or a loudness preset of a platform or standard
        ctk.CTkLabel(frame, text="Audio normalization:").grid(row=23, column=0, sticky="w", padx=10, pady=2)
        loudness_row = ctk.CTkFrame(frame, fg_color="transparent")
        loudness_row.grid(row=23, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        normalize_checkbox = ctk.CTkCheckBox(
            loudness_row,
            text="Normalize",
            variable=self.normalize_audio_var,
            command=self._update_loudness_menu
        )
        normalize_checkbox.grid(row=0, column=0)
        self.input_buttons.append(normalize_checkbox)
        self.loudness_menu = ctk.CTkOptionMenu(
            loudness_row,
            variable=self.loudness_preset_var,
            values=list(LOUDNESS_PRESETS),
            width=360
        )
        self.loudness_menu.grid(row=0, column=1, padx=(10, 0))
        self._update_loudness_menu()

        bottom = ctk.CTkFrame(root)
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=10)
        bottom.columnconfigure(1, weight=1)

        buttons = ctk.CTkFrame(bottom, fg_color="transparent")
        buttons.grid(row=0, column=0, columnspan=3, pady=(10, 5))
        self.run_button = ctk.CTkButton(buttons, text="Run", width=100, command=self._run)
        self.run_button.grid(row=0, column=0, padx=5)
        self.pause_button = ctk.CTkButton(buttons, text="Pause", width=100, state="disabled", command=self._toggle_pause)
        self.pause_button.grid(row=0, column=1, padx=5)
        self.stop_button = ctk.CTkButton(buttons, text="Stop", width=100, state="disabled", command=self._stop)
        self.stop_button.grid(row=0, column=2, padx=5)

        # Closing the window while rendering works like Stop
        self.closing = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Progress of the video currently being rendered
        ctk.CTkLabel(bottom, text="Current video:").grid(row=1, column=0, sticky="w", padx=10, pady=2)
        self.video_progress = ctk.CTkProgressBar(bottom, mode="determinate")
        self._set_bar(self.video_progress, 0)
        self.video_progress.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        ctk.CTkLabel(bottom, textvariable=self.video_percent_var).grid(row=1, column=2, sticky="w", padx=10, pady=2)
        # Stage the current video bar shows the progress of, e.g. "[1/3] Measuring loudness"
        self.video_stage_label = ctk.CTkLabel(bottom)
        self._set_video_stage(None)
        self.video_stage_label.grid(row=2, column=1, sticky="w", padx=5, pady=(0, 2))

        # Progress over all videos
        ctk.CTkLabel(bottom, text="Overall progress:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        self.progress = ctk.CTkProgressBar(bottom, mode="determinate")
        self._set_bar(self.progress, 0)
        self.progress.grid(row=3, column=1, sticky="ew", padx=5, pady=2)

        ctk.CTkLabel(bottom, textvariable=self.status_var).grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 10))

        # Find the video card encoder right away if "Use GPU" was on last time, to show its QP field
        if self.use_gpu_var.get():
            self._check_gpu()

        self._fit_window(frame, bottom)

    def _fit_window(self, settings_frame, bottom):
        # Open the window tall enough for all the settings, unless the screen is too short for that.
        # customtkinter sizes are set in unscaled units, while Tk reports scaled pixels
        self.root.update_idletasks()
        bottom_height = bottom.winfo_reqheight()
        max_height = self.root.winfo_screenheight() * MAX_WINDOW_SCREEN_SHARE - bottom_height
        settings_frame.configure(
            width=settings_frame._reverse_widget_scaling(settings_frame.winfo_reqwidth()),
            height=settings_frame._reverse_widget_scaling(min(settings_frame.winfo_reqheight(), max_height))
        )
        # The window can be made shorter, down to a few rows of settings
        self.root.update_idletasks()
        self.root.minsize(
            self.root._reverse_window_scaling(self.root.winfo_reqwidth()),
            self.root._reverse_window_scaling(bottom_height) + MIN_SETTINGS_HEIGHT
        )

    def _save_settings(self, *args):
        # Motion settings: those of a motion on its own under their names, the custom ones with a prefix
        motion_settings = {}
        for motion_vars in self.motion_vars.values():
            motion_settings.update({name: var.get() for name, var in motion_vars.items()})
        for motion, key in CUSTOM_MOTION_KEYS.items():
            for group in (self.custom_motion_vars[motion], self.custom_motion_state[motion]):
                motion_settings.update({f"custom_{key}_{name}": var.get() for name, var in group.items()})
        save_settings({
            "raw_videos_path": self.raw_videos_var.get(),
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": self.watermark_image_var.get(),
            "width_percent": self.width_var.get(),
            "height_percent": self.height_var.get(),
            "keep_aspect_ratio": self.keep_ratio_var.get(),
            "opacity_percent": self.opacity_var.get(),
            "watermark_motion": self.motion_var.get(),
            "custom_motion_order": self.custom_order_var.get(),
            **motion_settings,
            "video_quality": self.video_quality_var.get(),
            "crf": self.crf_var.get(),
            "gpu_qp": self.gpu_qp_var.get(),
            "gpu_qp_encoder": self.gpu_qp_encoder_var.get(),
            "bitrate_kbps": self.bitrate_var.get(),
            "normalize_audio": self.normalize_audio_var.get(),
            "loudness_preset": self.loudness_preset_var.get(),
            "video_codec": self.codec_var.get(),
            "use_gpu": self.use_gpu_var.get(),
        })

    def _add_number_field(self, parent, variable, max_value, allow_zero=False):
        # Entry for a number up to max_value (a number, or a function returning it)
        # with ▲/▼ buttons; returns the entry and the buttons.
        # The number is above zero, or zero too with allow_zero
        entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            width=70,
            validate="key",
            validatecommand=(
                self.root.register(lambda value: self._validate_number(variable, value, max_value)),
                "%P"
            )
        )
        entry.grid(row=0, column=0)

        arrows = ctk.CTkFrame(parent, fg_color="transparent")
        arrows.grid(row=0, column=1, padx=(3, 0))
        up = ctk.CTkButton(arrows, text="▲", width=22, height=13, font=("", 8),
                           command=lambda: self._step_number(entry, variable, max_value, 1, allow_zero))
        up.grid(row=0, column=0, pady=(0, 1))
        down = ctk.CTkButton(arrows, text="▼", width=22, height=13, font=("", 8),
                             command=lambda: self._step_number(entry, variable, max_value, -1, allow_zero))
        down.grid(row=1, column=0)

        # Up/Down keys and the mouse wheel change the value too
        entry.bind("<Up>", lambda e: self._step_number(entry, variable, max_value, 1, allow_zero))
        entry.bind("<Down>", lambda e: self._step_number(entry, variable, max_value, -1, allow_zero))
        entry.bind("<MouseWheel>", lambda e: self._wheel_number(entry, variable, max_value, 1 if e.delta > 0 else -1, allow_zero))
        entry.bind("<Button-4>", lambda e: self._wheel_number(entry, variable, max_value, 1, allow_zero))
        entry.bind("<Button-5>", lambda e: self._wheel_number(entry, variable, max_value, -1, allow_zero))

        self.input_entries.append(entry)
        self.input_buttons.extend((up, down))
        return entry, (up, down)

    def _validate_number(self, variable, value, max_value):
        if not NUMBER_INPUT_RE.fullmatch(value):
            return False
        max_value = max_value() if callable(max_value) else max_value
        number = parse_number(value)
        if number is not None and number > max_value:
            # Too large: reset the field to the maximum. Changing the variable inside
            # the validation would turn validation off, so do it right after
            self.root.after_idle(variable.set, format_number(max_value))
            return False
        return True

    def _wheel_number(self, entry, variable, max_value, direction, allow_zero):
        # The mouse wheel changes the value only while the field has the cursor,
        # otherwise it scrolls the settings, so scrolling past a field doesn't change it.
        # The CTkEntry frame holds the Tk entry that gets the focus
        focused = self.root.focus_get()
        if focused is None or not str(focused).startswith(str(entry) + "."):
            return None
        self._step_number(entry, variable, max_value, direction, allow_zero)
        # Don't scroll the settings as well
        return "break"

    def _step_number(self, entry, variable, max_value, direction, allow_zero=False):
        if entry.cget("state") == "disabled":
            return
        max_value = max_value() if callable(max_value) else max_value
        current = parse_number(variable.get()) or 0
        new = round(current + direction * NUMBER_STEP, 2)
        if allow_zero:
            # Stay within [0, max_value]: going below zero stops at zero
            new = max(new, 0)
        elif new <= 0:
            # Stay within (0, max_value]: going below zero keeps the current value
            return
        variable.set(format_number(min(new, max_value)))

    def _add_auto_field(self, parent, variable, max_value, label, auto_var, checkbox_text, auto_text, allow_zero=False):
        # Number field that auto_var switches to an automatic value, e.g. the height kept
        # from the aspect ratio or the original bitrate. With checkbox_text, a checkbox
        # controls auto_var; without it, the caller sets auto_var and calls _update_auto_field()
        entry, arrows = self._add_number_field(parent, variable, max_value, allow_zero)
        ctk.CTkLabel(parent, text=label).grid(row=0, column=2, padx=(5, 0))
        field = {
            "entry": entry,
            "arrows": arrows,
            "variable": variable,
            "auto_var": auto_var,
            # Shown in the field instead of the number while the checkbox is on
            "auto_text_var": ctk.StringVar(value=auto_text),
            "text_color": entry.cget("text_color"),
        }
        if checkbox_text is not None:
            checkbox = ctk.CTkCheckBox(
                parent,
                text=checkbox_text,
                variable=auto_var,
                command=lambda: self._update_auto_field(field)
            )
            checkbox.grid(row=0, column=3, padx=(20, 0))
            self.input_buttons.append(checkbox)
        self.auto_fields.append(field)
        self._update_auto_field(field)
        return field

    def _get_quality_mode_name(self, mode):
        # Name of the mode in the menu: constant quality is a QP on video cards
        return QUALITY_GPU_QP if mode == QUALITY_CRF and self.gpu_encoder is not None else mode

    def _select_quality_mode(self, name):
        self.video_quality_var.set(QUALITY_CRF if name == QUALITY_GPU_QP else name)
        self._update_quality_fields()

    def _update_quality_fields(self):
        # Show the CRF field for constant quality (the QP field when a video card encodes),
        # otherwise the bitrate field, which shows "original" in the "Same bitrate as original" mode
        mode = self.video_quality_var.get()
        self.quality_menu.configure(values=[self._get_quality_mode_name(m) for m in VIDEO_QUALITY_MODES])
        self.quality_menu.set(self._get_quality_mode_name(mode))
        if mode == QUALITY_CRF and self.gpu_encoder is not None:
            self.quality_value_label_var.set("Quality (QP):")
            self.bitrate_row.grid_remove()
            self.crf_row.grid_remove()
            self.gpu_qp_row.grid()
        elif mode == QUALITY_CRF:
            self.quality_value_label_var.set("Quality (CRF):")
            self.bitrate_row.grid_remove()
            self.gpu_qp_row.grid_remove()
            self.crf_row.grid()
        else:
            self.quality_value_label_var.set("Video bitrate:")
            self.crf_row.grid_remove()
            self.gpu_qp_row.grid_remove()
            self.bitrate_row.grid()
            self.original_bitrate_var.set(mode == QUALITY_ORIGINAL_BITRATE)
            self._update_auto_field(self.bitrate_field)

    def _load_motion_vars(self, settings, motion, prefix):
        # Variables of the settings of a motion, restored from the settings saved as prefix + field name
        motion_vars = {}
        for field in MOTION_FIELDS[motion]:
            motion_vars[field["name"]] = ctk.StringVar(value=valid_number_or(
                settings.get(prefix + field["name"]), str(field["default"]), field["max"], allow_zero="random" in field
            ))
            if "random" in field:
                motion_vars[field["random"]] = ctk.BooleanVar(
                    value=bool(settings.get(prefix + field["random"], field["random_default"]))
                )
        return motion_vars

    def _add_motion_rows(self, frame, row, motion, motion_vars, indent=False):
        # Rows of the settings of a motion from row on, indented under a custom section header;
        # returns their widgets, to show or hide them, and their fields with a random checkbox
        widgets = []
        auto_fields = []
        for i, field in enumerate(MOTION_FIELDS[motion]):
            label = ctk.CTkLabel(frame, text=field["label"] + ":")
            label.grid(row=row + i, column=0, sticky="w", padx=(30 if indent else 10, 10), pady=2)
            field_row = ctk.CTkFrame(frame, fg_color="transparent")
            field_row.grid(row=row + i, column=1, columnspan=2, sticky="w", padx=5, pady=2)
            if "random" in field:
                auto_fields.append(self._add_auto_field(
                    field_row, motion_vars[field["name"]], field["max"], field["hint"],
                    motion_vars[field["random"]], "Random for each video", "random", allow_zero=True
                ))
            else:
                self._add_number_field(field_row, motion_vars[field["name"]], field["max"])
                ctk.CTkLabel(field_row, text=field["hint"]).grid(row=0, column=2, padx=(5, 0))
            widgets += [label, field_row]
        return {"widgets": widgets, "auto_fields": auto_fields}

    def _add_custom_motion_header(self, frame, row, motion):
        # Header of a motion's section in the custom motion: a button that shows or hides its settings,
        # whether the motion is used, and its number in turn
        state = self.custom_motion_state[motion]
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=row, column=0, columnspan=3, sticky="ew", padx=5, pady=(6, 2))
        # Not locked while rendering: it only shows or hides the settings
        toggle = ctk.CTkButton(
            header,
            fg_color="transparent",
            hover_color=SECTION_HOVER_COLOR,
            text_color=ctk.ThemeManager.theme["CTkLabel"]["text_color"],
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
            width=260,
            command=lambda: self._toggle_custom_section(motion)
        )
        toggle.grid(row=0, column=0)
        use_checkbox = ctk.CTkCheckBox(header, text="Use", variable=state["use"], command=self._update_motion_fields)
        use_checkbox.grid(row=0, column=1, padx=(10, 0))
        self.input_buttons.append(use_checkbox)
        ctk.CTkLabel(header, text="Number in turn:").grid(row=0, column=2, padx=(20, 5))
        order_menu = ctk.CTkOptionMenu(
            header,
            variable=state["order"],
            values=[str(n) for n in range(1, len(CUSTOM_MOTION_KEYS) + 1)],
            width=70,
            command=lambda number: self._set_custom_order(motion)
        )
        order_menu.grid(row=0, column=3)
        self.input_buttons.append(order_menu)
        return {"frame": header, "toggle": toggle, "order_menu": order_menu}

    def _toggle_custom_section(self, motion):
        expanded = self.custom_motion_state[motion]["expanded"]
        expanded.set(not expanded.get())
        self._update_motion_fields()

    def _set_custom_order(self, motion):
        # The motion that had the chosen number takes the number left free, so the numbers don't repeat
        number = self.custom_motion_state[motion]["order"].get()
        free = {str(n) for n in range(1, len(CUSTOM_MOTION_KEYS) + 1)}
        free -= {state["order"].get() for state in self.custom_motion_state.values()}
        for other, state in self.custom_motion_state.items():
            if other != motion and state["order"].get() == number and free:
                state["order"].set(free.pop())

    def _update_motion_fields(self):
        # Show only the settings of the chosen motion: its rows when it's on its own,
        # or the custom order and the sections of the mixed motions, with the settings of the expanded ones
        motion = self.motion_var.get()
        custom_widgets = [self.custom_order_label, self.custom_order_menu]
        for section in self.custom_sections.values():
            custom_widgets += [section["header"]["frame"], *section["rows"]["widgets"]]
        for widget in [*custom_widgets, *(w for rows in self.motion_widgets.values() for w in rows["widgets"])]:
            widget.grid_remove()

        if motion in self.motion_widgets:
            for widget in self.motion_widgets[motion]["widgets"]:
                widget.grid()
        else:
            self.custom_order_label.grid()
            self.custom_order_menu.grid()
            for custom_motion, section in self.custom_sections.items():
                expanded = self.custom_motion_state[custom_motion]["expanded"].get()
                section["header"]["toggle"].configure(text=f"{'▼' if expanded else '▶'}  {custom_motion}")
                section["header"]["frame"].grid()
                if expanded:
                    for widget in section["rows"]["widgets"]:
                        widget.grid()
        self._update_custom_controls()

    def _update_custom_controls(self):
        # While idle, refresh the fields with a random checkbox (motions on their own share theirs,
        # so a field may be out of date) and allow a number in turn only where it's used
        if self.control is not None:
            return
        for rows in [*self.motion_widgets.values(), *(section["rows"] for section in self.custom_sections.values())]:
            for field in rows["auto_fields"]:
                self._update_auto_field(field)
        in_turn = self.custom_order_var.get() == CUSTOM_ORDER_IN_TURN
        for motion, section in self.custom_sections.items():
            used = self.custom_motion_state[motion]["use"].get()
            section["header"]["order_menu"].configure(state="normal" if in_turn and used else "disabled")

    def _update_auto_field(self, field):
        # The custom value is only used when the checkbox is off.
        # A disabled CTkEntry looks the same as an enabled one,
        # so also show the automatic value in gray instead of the custom one.
        # Switching the variable runs the input validation on that text, and Tk turns
        # validation off for good when it fails, so pause it during the switch
        entry = field["entry"]
        is_auto = field["auto_var"].get()
        entry.configure(validate="none")
        if is_auto:
            entry.configure(state="disabled", textvariable=field["auto_text_var"], text_color=DISABLED_TEXT_COLOR)
        else:
            entry.configure(state="normal", textvariable=field["variable"], text_color=field["text_color"])
        entry.configure(validate="key")
        for arrow in field["arrows"]:
            arrow.configure(state="disabled" if is_auto else "normal")

    def _parse_number(self, value, name, max_value, allow_zero=False):
        # Returns the field value as a number, or None after showing an error.
        # The number must be above zero, or may be zero too with allow_zero
        number = parse_number(value) if is_number_input(value, max_value) else None
        if number is None or number < 0 or (number == 0 and not allow_zero):
            lowest = "from 0" if allow_zero else "greater than 0 and"
            messagebox.showerror("Error", f"{name} must be a number {lowest} up to {format_number(max_value)}.")
            return None
        return number

    def _parse_motion_settings(self, motion, motion_vars, name_prefix):
        # Returns the add_watermark() settings of the motion from its fields, or None after showing
        # an error; a field with its random checkbox on gives None, a random value for each video
        settings = {"motion": motion}
        for field in MOTION_FIELDS[motion]:
            if "random" in field and motion_vars[field["random"]].get():
                settings[field["name"]] = None
                continue
            number = self._parse_number(
                motion_vars[field["name"]].get(), name_prefix + field["label"], field["max"],
                allow_zero="random" in field
            )
            if number is None:
                return None
            settings[field["name"]] = number
        return settings

    def _set_bar(self, bar, value):
        # customtkinter still draws a small rounded stub at 0,
        # so hide it by painting the progress part with the background color
        if not hasattr(bar, "default_progress_color"):
            bar.default_progress_color = bar.cget("progress_color")
        progress_color = bar.cget("fg_color") if value <= 0 else bar.default_progress_color
        bar.configure(progress_color=progress_color)
        bar.set(value)

    def _set_video_stage(self, stage):
        # Show the stage of the current video, or a gray placeholder (stage None) while no video is processed
        label = self.video_stage_label
        if not hasattr(label, "default_text_color"):
            label.default_text_color = label.cget("text_color")
        if stage is None:
            label.configure(text=VIDEO_STAGE_PLACEHOLDER, text_color=DISABLED_TEXT_COLOR)
        else:
            label.configure(text=stage, text_color=label.default_text_color)

    def _add_path_row(self, frame, row, label, variable, browse_command):
        ctk.CTkLabel(frame, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=(10 if row == 0 else 2, 2))
        entry = ctk.CTkEntry(frame, textvariable=variable, width=350)
        entry.grid(row=row, column=1, sticky="ew", padx=5, pady=(10 if row == 0 else 2, 2))
        button = ctk.CTkButton(frame, text="Browse…", width=90, command=browse_command)
        button.grid(row=row, column=2, padx=10, pady=(10 if row == 0 else 2, 2))
        self.input_entries.append(entry)
        self.input_buttons.append(button)

    def _set_inputs_enabled(self, enabled):
        # Lock or unlock the settings; a disabled CTkEntry looks the same
        # as an enabled one, so also gray out its text
        state = "normal" if enabled else "disabled"
        auto_entries = [field["entry"] for field in self.auto_fields]
        auto_arrows = [arrow for field in self.auto_fields for arrow in field["arrows"]]
        for entry in self.input_entries:
            if entry in auto_entries:
                continue
            if not hasattr(entry, "default_text_color"):
                entry.default_text_color = entry.cget("text_color")
            entry.configure(state=state, text_color=entry.default_text_color if enabled else DISABLED_TEXT_COLOR)
        for button in self.input_buttons:
            if button in auto_arrows:
                continue
            button.configure(state=state)

        # Fields with an automatic value also depend on their checkbox
        for field in self.auto_fields:
            if enabled:
                self._update_auto_field(field)
            else:
                field["entry"].configure(state="disabled", text_color=DISABLED_TEXT_COLOR)
                for arrow in field["arrows"]:
                    arrow.configure(state="disabled")

        # The loudness preset menu also depends on the "Normalize" checkbox
        if enabled:
            self._update_loudness_menu()
        else:
            self.loudness_menu.configure(state="disabled")

        # The numbers in turn of the custom motion also depend on the order and the "Use" checkboxes
        if enabled:
            self._update_custom_controls()

    def _check_gpu(self):
        # Show which encoder the chosen codec will use; when "Use GPU" is on,
        # make sure a video card encoder actually works. The checks are cached
        codec = self.codec_var.get()
        self.status_var.set("Checking the encoders…")
        self.root.update_idletasks()

        cpu_encoder = find_cpu_encoder(codec)
        cpu_status = f"CPU encoder: {cpu_encoder[1]}" if cpu_encoder else f"No {codec} encoder found"
        if not self.use_gpu_var.get():
            self.status_var.set(cpu_status)
            self._set_gpu_encoder(None)
            return

        gpu_encoder = find_gpu_encoder(codec)
        self._set_gpu_encoder(gpu_encoder[1] if gpu_encoder is not None else None)
        if gpu_encoder is not None:
            self.status_var.set(f"Video card encoder: {gpu_encoder[1]}")
        elif any(find_gpu_encoder(other) for other in VIDEO_CODECS if other != codec):
            # The video card works, just not with this codec: keep "Use GPU" for the other codecs
            self.status_var.set(f"The video card can't encode this codec, so the CPU is used. {cpu_status}")
        else:
            self.use_gpu_var.set(False)
            self.status_var.set(cpu_status)
            messagebox.showinfo(
                "Use GPU",
                "No supported video card encoder was found, so the CPU will be used.\n\n"
                "Supported: NVIDIA (NVENC), Intel (Quick Sync), AMD (AMF on Windows, VAAPI on Linux)."
            )

    def _set_gpu_encoder(self, encoder):
        # Set up the QP field for the video card encoder, or hide it for None
        self.gpu_encoder = encoder
        if encoder is not None:
            recommended, self.gpu_qp_max = get_gpu_qp_scale(encoder)
            # Encoders have different scales, so a QP set for another one means nothing here
            if self.gpu_qp_encoder_var.get() != encoder or not self.gpu_qp_var.get():
                self.gpu_qp_var.set(str(recommended))
                self.gpu_qp_encoder_var.set(encoder)
            self.gpu_qp_hint_var.set(
                f"{encoder} scale, lower = better quality, {recommended} recommended (max: {self.gpu_qp_max})"
            )
        self._update_quality_fields()

    def _update_loudness_menu(self):
        # A preset can only be chosen while normalization is on
        self.loudness_menu.configure(state="normal" if self.normalize_audio_var.get() else "disabled")

    def _browse_raw_videos(self):
        path = filedialog.askdirectory(title="Select raw videos folder")
        if path:
            self.raw_videos_var.set(path)

    def _browse_output_folder(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_folder_var.set(path)

    def _browse_watermark(self):
        path = filedialog.askopenfilename(
            title="Select watermark image",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*")]
        )
        if path:
            self.watermark_image_var.set(path)

    def _run(self):
        raw_videos_path = self.raw_videos_var.get()
        output_folder_path = self.output_folder_var.get()
        watermark_image_path = self.watermark_image_var.get()

        # Validate the paths before starting
        if not os.path.isdir(raw_videos_path):
            messagebox.showerror("Error", f"Raw videos folder not found:\n{raw_videos_path}")
            return
        if not os.path.isfile(watermark_image_path):
            messagebox.showerror("Error", f"Watermark image not found:\n{watermark_image_path}")
            return

        # Validate the watermark size
        width_percent = self._parse_number(self.width_var.get(), "Watermark width", MAX_PERCENT)
        if width_percent is None:
            return
        if self.keep_ratio_var.get():
            height_percent = None
        else:
            height_percent = self._parse_number(self.height_var.get(), "Watermark height", MAX_PERCENT)
            if height_percent is None:
                return

        # Validate the watermark opacity
        opacity_percent = self._parse_number(self.opacity_var.get(), "Watermark opacity", MAX_PERCENT)
        if opacity_percent is None:
            return

        # Validate the settings of the chosen motion; the hidden ones of the other motions aren't used
        motion = self.motion_var.get()
        random_motion_order = False
        if motion in self.motion_vars:
            motion_settings = self._parse_motion_settings(motion, self.motion_vars[motion], "")
            if motion_settings is None:
                return
            motions = [motion_settings]
        else:
            # Custom: the used motions in turn by their numbers, or each video takes a random one
            used = [m for m in CUSTOM_MOTION_KEYS if self.custom_motion_state[m]["use"].get()]
            if not used:
                messagebox.showerror("Error", "Custom motion: turn on \"Use\" for at least one motion.")
                return
            used.sort(key=lambda m: int(self.custom_motion_state[m]["order"].get()))
            motions = []
            for custom_motion in used:
                motion_settings = self._parse_motion_settings(
                    custom_motion, self.custom_motion_vars[custom_motion], f"{custom_motion}: "
                )
                if motion_settings is None:
                    return
                motions.append(motion_settings)
            random_motion_order = self.custom_order_var.get() == CUSTOM_ORDER_RANDOM

        # Validate the video quality: a CRF, or a bitrate (None keeps the bitrate of each original video)
        mode = self.video_quality_var.get()
        crf = None
        qp = None
        bitrate_kbps = None
        if mode == QUALITY_CRF:
            # The CRF is also needed with a video card: the CPU takes over the videos it can't encode
            crf = self._parse_number(self.crf_var.get(), "Quality (CRF)", MAX_CRF)
            if crf is None:
                return
            if self.gpu_encoder is not None:
                qp = self._parse_number(self.gpu_qp_var.get(), "Quality (QP)", self.gpu_qp_max)
                if qp is None:
                    return
        elif mode == QUALITY_CUSTOM_BITRATE:
            bitrate_kbps = self._parse_number(self.bitrate_var.get(), "Video bitrate", MAX_BITRATE_KBPS)
            if bitrate_kbps is None:
                return

        # Loudness to normalize the audio to; None keeps the original audio
        if self.normalize_audio_var.get():
            target_lufs = LOUDNESS_PRESETS[self.loudness_preset_var.get()]
        else:
            target_lufs = None

        self.control = RenderControl()
        self.paused = False
        self.processing_status = "Starting…"
        self.run_button.configure(state="disabled")
        self._set_inputs_enabled(False)
        self.pause_button.configure(state="normal", text="Pause")
        self.stop_button.configure(state="normal")
        self._set_bar(self.progress, 0)
        self._set_bar(self.video_progress, 0)
        self.video_percent_var.set("0%")
        self._set_video_stage(None)
        self.status_var.set("Starting…")

        # Render in a background thread so the window doesn't freeze
        thread = threading.Thread(
            target=self._process,
            args=(raw_videos_path, output_folder_path, watermark_image_path, self.control,
                  width_percent, height_percent, opacity_percent, motions, random_motion_order,
                  bitrate_kbps, target_lufs, crf,
                  self.use_gpu_var.get(), self.codec_var.get(), qp),
            daemon=True
        )
        thread.start()

    def _toggle_pause(self):
        if self.paused:
            self.control.resume()
            self.paused = False
            self.pause_button.configure(text="Pause")
            self.status_var.set(self.processing_status)
        else:
            self.control.pause()
            self.paused = True
            self.pause_button.configure(text="Resume")
            self.status_var.set("Paused")

    def _stop(self):
        self.control.stop()
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_var.set("Stopping…")

    def _on_close(self):
        if self.control is None:
            self.root.destroy()
            return

        # Stop rendering and close the window once the partial files are removed
        self.closing = True
        if not self.control.stopped:
            self._stop()

    def _close_if_requested(self):
        # Called when rendering ends; returns True if the window was closed
        if self.closing:
            self.root.destroy()
            return True
        return False

    def _finish(self):
        # Return the buttons to the idle state
        self.control = None
        self.paused = False
        self.run_button.configure(state="normal")
        self._set_inputs_enabled(True)
        self.pause_button.configure(state="disabled", text="Pause")
        self.stop_button.configure(state="disabled")
        self._set_video_stage(None)

    def _process(self, raw_videos_path, output_folder_path, watermark_image_path, control,
                 width_percent, height_percent, opacity_percent, motions, random_motion_order,
                 bitrate_kbps, target_lufs, crf,
                 use_gpu, codec, qp):
        try:
            main(
                raw_videos_path,
                output_folder_path,
                watermark_image_path,
                on_progress=self._on_progress,
                on_video_progress=self._on_video_progress,
                control=control,
                width_percent=width_percent,
                height_percent=height_percent,
                opacity_percent=opacity_percent,
                motions=motions,
                random_motion_order=random_motion_order,
                bitrate_kbps=bitrate_kbps,
                target_lufs=target_lufs,
                crf=crf,
                use_gpu=use_gpu,
                codec=codec,
                qp=qp
            )
        except RenderCancelled:
            self.root.after(0, self._on_cancelled)
        except Exception as e:
            self.root.after(0, self._on_error, e)
        else:
            self.root.after(0, self._on_done)

    def _on_progress(self, index, total, video_file):
        # Called from the worker thread, so hand the UI update to the main thread
        self.root.after(0, self._update_progress, index, total, video_file)

    def _update_progress(self, processed, total, video_file):
        # Avoid division by zero when the folder has no videos
        self._set_bar(self.progress, processed / max(total, 1))

        if video_file is not None:
            self._set_bar(self.video_progress, 0)
            self.video_percent_var.set("0%")
            self._set_video_stage(None)
            # Remember the status to restore it after resuming from pause
            self.processing_status = f"Processing video {processed + 1} of {total}: {video_file}"
            self.status_var.set(self.processing_status)

    def _on_video_progress(self, stage, percent):
        # Called from the worker thread, so hand the UI update to the main thread
        self.root.after(0, self._update_video_progress, stage, percent)

    def _update_video_progress(self, stage, percent):
        self._set_bar(self.video_progress, percent / 100)
        self.video_percent_var.set(f"{percent}%")
        self._set_video_stage(stage)

    def _on_done(self):
        if self._close_if_requested():
            return
        self.status_var.set("Done")
        self._finish()
        messagebox.showinfo("Done", "All videos have been processed.")

    def _on_cancelled(self):
        if self._close_if_requested():
            return
        self.status_var.set("Stopped")
        self._set_bar(self.video_progress, 0)
        self.video_percent_var.set("0%")
        self._finish()

    def _on_error(self, error):
        if self._close_if_requested():
            print(f"Error: {error}")
            return
        self.status_var.set("Error")
        self._finish()
        messagebox.showerror("Error", str(error))


def run():
    # Follow the system light/dark theme
    ctk.set_appearance_mode("system")

    root = ctk.CTk()
    WatermarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
