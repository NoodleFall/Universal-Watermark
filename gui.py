import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from constants import (
    APP_NAME,
    DEFAULT_BOUNCE_SPEED_PERCENT,
    DEFAULT_POSITION_CHANGE_SECONDS,
    DISABLED_TEXT_COLOR,
    LOUDNESS_PRESETS,
    MAX_BITRATE_KBPS,
    MAX_CRF,
    MAX_GPU_QP,
    MAX_PERCENT,
    MAX_POSITION_CHANGE_SECONDS,
    MAX_TRAVEL_TIME_SECONDS,
    MAX_WINDOW_SCREEN_SHARE,
    MIN_SETTINGS_HEIGHT,
    MAX_BOUNCE_SPEED_PERCENT,
    MOTION_BOUNCE,
    NUMBER_INPUT_RE,
    NUMBER_STEP,
    QUALITY_CRF,
    QUALITY_CUSTOM_BITRATE,
    QUALITY_GPU_QP,
    QUALITY_ORIGINAL_BITRATE,
    RECOMMENDED_CRF,
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
        self.travel_time_var = ctk.StringVar(
            value=valid_number_or(settings.get("travel_time_seconds"), "30", MAX_TRAVEL_TIME_SECONDS)
        )
        self.position_change_var = ctk.StringVar(value=valid_number_or(
            settings.get("position_change_seconds"), str(DEFAULT_POSITION_CHANGE_SECONDS), MAX_POSITION_CHANGE_SECONDS
        ))
        self.start_position_var = ctk.StringVar(
            value=valid_number_or(settings.get("start_position_percent"), "0", MAX_PERCENT, allow_zero=True)
        )
        self.random_start_var = ctk.BooleanVar(value=bool(settings.get("random_start_position", False)))
        self.motion_var = ctk.StringVar(value=find_watermark_motion(settings.get("watermark_motion")))
        self.bounce_speed_var = ctk.StringVar(value=valid_number_or(
            settings.get("bounce_speed_percent"), str(DEFAULT_BOUNCE_SPEED_PERCENT), MAX_BOUNCE_SPEED_PERCENT
        ))
        self.horizontal_start_var = ctk.StringVar(
            value=valid_number_or(settings.get("horizontal_start_percent"), "0", MAX_PERCENT, allow_zero=True)
        )
        # Random by default: the bouncing watermark always started at a random horizontal position before
        self.random_horizontal_start_var = ctk.BooleanVar(value=bool(settings.get("random_horizontal_start", True)))
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

        # Save the settings whenever any of them changes
        for var in (self.raw_videos_var, self.output_folder_var, self.watermark_image_var,
                    self.width_var, self.height_var, self.keep_ratio_var, self.opacity_var,
                    self.motion_var, self.travel_time_var, self.start_position_var, self.random_start_var,
                    self.bounce_speed_var, self.horizontal_start_var, self.random_horizontal_start_var,
                    self.position_change_var, self.video_quality_var, self.crf_var, self.bitrate_var,
                    self.gpu_qp_var, self.gpu_qp_encoder_var,
                    self.codec_var, self.use_gpu_var, self.normalize_audio_var, self.loudness_preset_var):
            var.trace_add("write", self._save_settings)

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

        # Settings of only one motion share a row with those of the other one; _update_motion_fields()
        # shows the right ones. Top to bottom: the time to travel from the top to the bottom of the video
        travel_time_label = ctk.CTkLabel(frame, text="Travel time:")
        travel_time_label.grid(row=7, column=0, sticky="w", padx=10, pady=2)
        travel_time_row = ctk.CTkFrame(frame, fg_color="transparent")
        travel_time_row.grid(row=7, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(travel_time_row, self.travel_time_var, MAX_TRAVEL_TIME_SECONDS)
        ctk.CTkLabel(
            travel_time_row,
            text=f"seconds from top to bottom (max: {MAX_TRAVEL_TIME_SECONDS})"
        ).grid(row=0, column=2, padx=(5, 0))

        # Bounce: the speed as a percentage of the video height per second, the same
        # in pixels on both axes, so it looks the same for any resolution
        speed_label = ctk.CTkLabel(frame, text="Speed:")
        speed_label.grid(row=7, column=0, sticky="w", padx=10, pady=2)
        speed_row = ctk.CTkFrame(frame, fg_color="transparent")
        speed_row.grid(row=7, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(speed_row, self.bounce_speed_var, MAX_BOUNCE_SPEED_PERCENT)
        ctk.CTkLabel(
            speed_row,
            text=f"% of video height per second (max: {MAX_BOUNCE_SPEED_PERCENT})"
        ).grid(row=0, column=2, padx=(5, 0))

        # Vertical position of the watermark at the start of each video, as a percentage
        # of its travel from the top, so it means the same for any resolution; or a random one
        self.start_position_label = ctk.CTkLabel(frame)
        self.start_position_label.grid(row=8, column=0, sticky="w", padx=10, pady=2)
        start_position_row = ctk.CTkFrame(frame, fg_color="transparent")
        start_position_row.grid(row=8, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_auto_field(
            start_position_row, self.start_position_var, MAX_PERCENT, f"% from the top (0 = top, {MAX_PERCENT} = bottom)",
            self.random_start_var, "Random for each video", "random", allow_zero=True
        )

        # Top to bottom: how often the watermark jumps to a new random horizontal position
        position_change_label = ctk.CTkLabel(frame, text="Position change:")
        position_change_label.grid(row=9, column=0, sticky="w", padx=10, pady=2)
        position_change_row = ctk.CTkFrame(frame, fg_color="transparent")
        position_change_row.grid(row=9, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(position_change_row, self.position_change_var, MAX_POSITION_CHANGE_SECONDS)
        ctk.CTkLabel(
            position_change_row,
            text=f"seconds between horizontal jumps (max: {MAX_POSITION_CHANGE_SECONDS})"
        ).grid(row=0, column=2, padx=(5, 0))

        # Bounce: horizontal position at the start of each video, as a percentage of
        # the travel from the left; or a random one
        horizontal_start_label = ctk.CTkLabel(frame, text="Horizontal start:")
        horizontal_start_label.grid(row=9, column=0, sticky="w", padx=10, pady=2)
        horizontal_start_row = ctk.CTkFrame(frame, fg_color="transparent")
        horizontal_start_row.grid(row=9, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_auto_field(
            horizontal_start_row, self.horizontal_start_var, MAX_PERCENT,
            f"% from the left (0 = left, {MAX_PERCENT} = right)",
            self.random_horizontal_start_var, "Random for each video", "random", allow_zero=True
        )

        # Widgets shown only for one motion
        self.top_to_bottom_widgets = (travel_time_label, travel_time_row, position_change_label, position_change_row)
        self.bounce_widgets = (speed_label, speed_row, horizontal_start_label, horizontal_start_row)
        self._update_motion_fields()

        # Video codec: H.264, HEVC or AV1
        ctk.CTkLabel(frame, text="Video codec:").grid(row=10, column=0, sticky="w", padx=10, pady=2)
        codec_row = ctk.CTkFrame(frame, fg_color="transparent")
        codec_row.grid(row=10, column=1, columnspan=2, sticky="w", padx=5, pady=2)
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
        ctk.CTkLabel(frame, text="Video quality:").grid(row=11, column=0, sticky="w", padx=10, pady=2)
        # The menu shows display names: the constant quality mode reads "(QP)" while a video
        # card encodes; video_quality_var keeps the mode itself, as saved in the settings
        self.quality_menu = ctk.CTkOptionMenu(
            frame,
            values=list(VIDEO_QUALITY_MODES),
            width=220,
            command=self._select_quality_mode
        )
        self.quality_menu.grid(row=11, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.input_buttons.append(self.quality_menu)

        # Value of the chosen quality mode: the CRF or the bitrate field, in the same place
        self.quality_value_label_var = ctk.StringVar()
        ctk.CTkLabel(frame, textvariable=self.quality_value_label_var).grid(row=12, column=0, sticky="w", padx=10, pady=2)
        self.crf_row = ctk.CTkFrame(frame, fg_color="transparent")
        self.crf_row.grid(row=12, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(self.crf_row, self.crf_var, MAX_CRF)
        ctk.CTkLabel(
            self.crf_row,
            text=f"lower = better quality, {RECOMMENDED_CRF} recommended (max: {MAX_CRF})"
        ).grid(row=0, column=2, padx=(5, 0))
        # QP of the video card, shown instead of the CRF when it encodes the video;
        # its highest value depends on the encoder
        self.gpu_qp_row = ctk.CTkFrame(frame, fg_color="transparent")
        self.gpu_qp_row.grid(row=12, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_number_field(self.gpu_qp_row, self.gpu_qp_var, lambda: self.gpu_qp_max)
        self.gpu_qp_hint_var = ctk.StringVar()
        ctk.CTkLabel(self.gpu_qp_row, textvariable=self.gpu_qp_hint_var).grid(row=0, column=2, padx=(5, 0))
        self.bitrate_row = ctk.CTkFrame(frame, fg_color="transparent")
        self.bitrate_row.grid(row=12, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.bitrate_field = self._add_auto_field(
            self.bitrate_row, self.bitrate_var, MAX_BITRATE_KBPS, f"kb/s (max: {MAX_BITRATE_KBPS})",
            self.original_bitrate_var, None, "original"
        )
        self._update_quality_fields()

        # Audio normalization: off, or a loudness preset of a platform or standard
        ctk.CTkLabel(frame, text="Audio normalization:").grid(row=13, column=0, sticky="w", padx=10, pady=2)
        loudness_row = ctk.CTkFrame(frame, fg_color="transparent")
        loudness_row.grid(row=13, column=1, columnspan=2, sticky="w", padx=5, pady=2)
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

        # Pause/stop control of the current rendering, None when idle
        self.control = None
        self.paused = False

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
        save_settings({
            "raw_videos_path": self.raw_videos_var.get(),
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": self.watermark_image_var.get(),
            "width_percent": self.width_var.get(),
            "height_percent": self.height_var.get(),
            "keep_aspect_ratio": self.keep_ratio_var.get(),
            "opacity_percent": self.opacity_var.get(),
            "travel_time_seconds": self.travel_time_var.get(),
            "watermark_motion": self.motion_var.get(),
            "start_position_percent": self.start_position_var.get(),
            "random_start_position": self.random_start_var.get(),
            "bounce_speed_percent": self.bounce_speed_var.get(),
            "horizontal_start_percent": self.horizontal_start_var.get(),
            "random_horizontal_start": self.random_horizontal_start_var.get(),
            "position_change_seconds": self.position_change_var.get(),
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

    def _update_motion_fields(self):
        # Show only the settings of the chosen motion
        bounce = self.motion_var.get() == MOTION_BOUNCE
        shown, hidden = (
            (self.bounce_widgets, self.top_to_bottom_widgets) if bounce
            else (self.top_to_bottom_widgets, self.bounce_widgets)
        )
        for widget in hidden:
            widget.grid_remove()
        for widget in shown:
            widget.grid()
        # The bounce motion has a horizontal start too, so name this one vertical
        self.start_position_label.configure(text="Vertical start:" if bounce else "Start position:")

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

        # Validate the settings of the chosen motion; the hidden ones of the other motion aren't used
        motion = self.motion_var.get()
        travel_time_seconds = None
        position_change_seconds = DEFAULT_POSITION_CHANGE_SECONDS
        bounce_speed_percent = DEFAULT_BOUNCE_SPEED_PERCENT
        horizontal_start_percent = None
        if motion == MOTION_BOUNCE:
            bounce_speed_percent = self._parse_number(self.bounce_speed_var.get(), "Speed", MAX_BOUNCE_SPEED_PERCENT)
            if bounce_speed_percent is None:
                return
            # None picks a random horizontal start for each video
            if not self.random_horizontal_start_var.get():
                horizontal_start_percent = self._parse_number(
                    self.horizontal_start_var.get(), "Horizontal start", MAX_PERCENT, allow_zero=True
                )
                if horizontal_start_percent is None:
                    return
        else:
            travel_time_seconds = self._parse_number(self.travel_time_var.get(), "Travel time", MAX_TRAVEL_TIME_SECONDS)
            if travel_time_seconds is None:
                return
            # How often the watermark changes its horizontal position
            position_change_seconds = self._parse_number(
                self.position_change_var.get(), "Position change", MAX_POSITION_CHANGE_SECONDS
            )
            if position_change_seconds is None:
                return

        # Validate the vertical start position; None picks a random one for each video
        if self.random_start_var.get():
            start_position_percent = None
        else:
            start_position_percent = self._parse_number(
                self.start_position_var.get(), self.start_position_label.cget("text").rstrip(":"), MAX_PERCENT,
                allow_zero=True
            )
            if start_position_percent is None:
                return

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
                  width_percent, height_percent, opacity_percent, travel_time_seconds, position_change_seconds,
                  start_position_percent, motion, bounce_speed_percent, horizontal_start_percent,
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
                 width_percent, height_percent, opacity_percent, travel_time_seconds, position_change_seconds,
                 start_position_percent, motion, bounce_speed_percent, horizontal_start_percent,
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
                travel_time_seconds=travel_time_seconds,
                position_change_seconds=position_change_seconds,
                start_position_percent=start_position_percent,
                motion=motion,
                bounce_speed_percent=bounce_speed_percent,
                horizontal_start_percent=horizontal_start_percent,
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
