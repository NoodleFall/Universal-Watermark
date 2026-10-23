import os
from tkinter import filedialog, messagebox

import customtkinter as ctk

from constants import (
    LOUDNESS_PRESETS,
    MAX_BITRATE_KBPS,
    MAX_CRF,
    MAX_GPU_QP,
    MAX_PERCENT,
    QUALITY_CRF,
    QUALITY_CUSTOM_BITRATE,
    QUALITY_GPU_QP,
    QUALITY_ORIGINAL_BITRATE,
    RECOMMENDED_CRF,
    VIDEO_CODECS,
    VIDEO_QUALITY_MODES,
)
from functions.encoders import find_cpu_encoder, find_gpu_encoder, get_gpu_qp_scale
from ui.fields import AutoNumberField, NumberField, add_inputs_frame, add_setting_row
from ui.number_input import InvalidInput, parse_field, valid_number_or
from ui.settings import find_codec, find_loudness_preset, find_video_quality_mode

# Each section places its rows in the settings grid from row on (next_row is the first one after them),
# lists its variables to save on change, returns its settings to save and checks them before rendering


class PathsSection:
    """Folder of the raw videos, output folder and watermark image, each with a "Browse…" button."""

    def __init__(self, frame, row, lock, saved):
        self.raw_videos_var = ctk.StringVar(value=saved.get("raw_videos_path", "raw_videos"))
        self.output_folder_var = ctk.StringVar(value=saved.get("output_folder_path", "watermarked_videos"))
        self.watermark_image_var = ctk.StringVar(value=saved.get("watermark_image_path", "watermark.png"))

        self._add_path_row(frame, row, lock, "Raw videos folder:", self.raw_videos_var, self._browse_raw_videos)
        self._add_path_row(frame, row + 1, lock, "Output folder:", self.output_folder_var, self._browse_output_folder)
        self._add_path_row(frame, row + 2, lock, "Watermark image:", self.watermark_image_var, self._browse_watermark)
        self.next_row = row + 3

    @staticmethod
    def _add_path_row(frame, row, lock, label, variable, browse_command):
        pady = (10 if row == 0 else 2, 2)
        ctk.CTkLabel(frame, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=pady)
        entry = ctk.CTkEntry(frame, textvariable=variable, width=350)
        entry.grid(row=row, column=1, sticky="ew", padx=5, pady=pady)
        button = ctk.CTkButton(frame, text="Browse…", width=90, command=browse_command)
        button.grid(row=row, column=2, padx=10, pady=pady)
        lock.add(entry, button)

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

    def variables(self):
        return [self.raw_videos_var, self.output_folder_var, self.watermark_image_var]

    def settings(self):
        return {
            "raw_videos_path": self.raw_videos_var.get(),
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": self.watermark_image_var.get(),
        }

    def parse(self):
        # Returns the paths for main(), or raises InvalidInput if the input folder or image is missing
        raw_videos_path = self.raw_videos_var.get()
        watermark_image_path = self.watermark_image_var.get()
        if not os.path.isdir(raw_videos_path):
            raise InvalidInput(f"Raw videos folder not found:\n{raw_videos_path}")
        if not os.path.isfile(watermark_image_path):
            raise InvalidInput(f"Watermark image not found:\n{watermark_image_path}")
        return {
            "raw_videos_path": raw_videos_path,
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": watermark_image_path,
        }


class WatermarkLookSection:
    """Watermark size, as percentages of the video size, and opacity."""

    def __init__(self, frame, row, lock, saved):
        self.width_var = ctk.StringVar(value=valid_number_or(saved.get("width_percent"), "50", MAX_PERCENT))
        self.height_var = ctk.StringVar(value=valid_number_or(saved.get("height_percent"), "20", MAX_PERCENT))
        self.keep_ratio_var = ctk.BooleanVar(value=bool(saved.get("keep_aspect_ratio", True)))
        self.opacity_var = ctk.StringVar(value=valid_number_or(saved.get("opacity_percent"), "33", MAX_PERCENT))

        # Width as a percentage of the video width
        _, inputs = add_setting_row(frame, row, "Watermark width:")
        NumberField(inputs, lock, self.width_var, MAX_PERCENT, f"% of video width (max: {MAX_PERCENT})")
        # Height: derived from the width, or a custom percentage of the video height
        _, inputs = add_setting_row(frame, row + 1, "Watermark height:")
        AutoNumberField(
            inputs, lock, self.height_var, MAX_PERCENT, f"% of video height (max: {MAX_PERCENT})",
            self.keep_ratio_var, "Keep aspect ratio", "auto"
        )
        # Opacity: 100% is fully opaque
        _, inputs = add_setting_row(frame, row + 2, "Watermark opacity:")
        NumberField(inputs, lock, self.opacity_var, MAX_PERCENT, f"% (max: {MAX_PERCENT})")
        self.next_row = row + 3

    def variables(self):
        return [self.width_var, self.height_var, self.keep_ratio_var, self.opacity_var]

    def settings(self):
        return {
            "width_percent": self.width_var.get(),
            "height_percent": self.height_var.get(),
            "keep_aspect_ratio": self.keep_ratio_var.get(),
            "opacity_percent": self.opacity_var.get(),
        }

    def parse(self):
        # Returns the size and opacity for main(), or raises InvalidInput
        return {
            "width_percent": parse_field(self.width_var.get(), "Watermark width", MAX_PERCENT),
            # None keeps the aspect ratio of the image
            "height_percent": None if self.keep_ratio_var.get()
            else parse_field(self.height_var.get(), "Watermark height", MAX_PERCENT),
            "opacity_percent": parse_field(self.opacity_var.get(), "Watermark opacity", MAX_PERCENT),
        }


class EncodingSection:
    """
    Video codec, encoding on the video card, video quality (CRF, QP of the video card,
    or a bitrate) and audio normalization. set_status shows a message in the status line.
    """

    def __init__(self, frame, row, lock, saved, set_status):
        self.frame = frame
        self.set_status = set_status
        self.codec_var = ctk.StringVar(value=find_codec(saved.get("video_codec")))
        self.use_gpu_var = ctk.BooleanVar(value=bool(saved.get("use_gpu", False)))
        self.video_quality_var = ctk.StringVar(value=find_video_quality_mode(saved))
        self.crf_var = ctk.StringVar(value=valid_number_or(saved.get("crf"), str(RECOMMENDED_CRF), MAX_CRF))
        self.bitrate_var = ctk.StringVar(value=valid_number_or(saved.get("bitrate_kbps"), "8000", MAX_BITRATE_KBPS))
        # QP of the video card encoder on its own scale, and the encoder it was set for
        self.gpu_qp_var = ctk.StringVar(value=valid_number_or(saved.get("gpu_qp"), "", MAX_GPU_QP))
        self.gpu_qp_encoder_var = ctk.StringVar(value=saved.get("gpu_qp_encoder", ""))
        self.normalize_audio_var = ctk.BooleanVar(value=bool(saved.get("normalize_audio", False)))
        self.loudness_preset_var = ctk.StringVar(value=find_loudness_preset(saved.get("loudness_preset")))
        # Video card encoder used for the chosen codec, or None; set by check_gpu()
        self.gpu_encoder = None
        self.gpu_qp_max = MAX_GPU_QP
        # Shows "original" in the bitrate field; set from the video quality mode
        self.original_bitrate_var = ctk.BooleanVar()

        # Video codec: H.264, HEVC or AV1, and whether the video card encodes it:
        # faster, but usually bigger files for the same quality
        _, inputs = add_setting_row(frame, row, "Video codec:")
        codec_menu = ctk.CTkOptionMenu(
            inputs, variable=self.codec_var, values=list(VIDEO_CODECS), width=260,
            command=lambda codec: self.check_gpu()
        )
        codec_menu.grid(row=0, column=0)
        gpu_checkbox = ctk.CTkCheckBox(
            inputs, text="Use GPU (faster, bigger files)", variable=self.use_gpu_var, command=self.check_gpu
        )
        gpu_checkbox.grid(row=0, column=1, padx=(20, 0))
        lock.add(codec_menu, gpu_checkbox)

        # Video quality: constant quality (CRF), the bitrate of each original video, or a custom bitrate.
        # The menu shows display names: the constant quality mode reads "(QP)" while a video
        # card encodes; video_quality_var keeps the mode itself, as saved in the settings
        _, inputs = add_setting_row(frame, row + 1, "Video quality:")
        self.quality_menu = ctk.CTkOptionMenu(
            inputs, values=list(VIDEO_QUALITY_MODES), width=220, command=self._select_quality_mode
        )
        self.quality_menu.grid(row=0, column=0)
        lock.add(self.quality_menu)

        # Value of the chosen quality mode: the CRF, QP or bitrate field, in the same place
        self.quality_value_label, self.crf_row = add_setting_row(frame, row + 2, "")
        NumberField(
            self.crf_row, lock, self.crf_var, MAX_CRF,
            f"lower = better quality, {RECOMMENDED_CRF} recommended (max: {MAX_CRF})"
        )
        # QP of the video card, shown instead of the CRF when it encodes the video;
        # its highest value depends on the encoder
        self.gpu_qp_row = add_inputs_frame(frame, row + 2)
        NumberField(self.gpu_qp_row, lock, self.gpu_qp_var, lambda: self.gpu_qp_max)
        self.gpu_qp_hint_var = ctk.StringVar()
        ctk.CTkLabel(self.gpu_qp_row, textvariable=self.gpu_qp_hint_var).grid(row=0, column=2, padx=(5, 0))
        self.bitrate_row = add_inputs_frame(frame, row + 2)
        self.bitrate_field = AutoNumberField(
            self.bitrate_row, lock, self.bitrate_var, MAX_BITRATE_KBPS, f"kb/s (max: {MAX_BITRATE_KBPS})",
            self.original_bitrate_var, None, "original"
        )
        self._update_quality_fields()

        # Audio normalization: off, or a loudness preset of a platform or standard
        _, inputs = add_setting_row(frame, row + 3, "Audio normalization:")
        normalize_checkbox = ctk.CTkCheckBox(
            inputs, text="Normalize", variable=self.normalize_audio_var, command=self._update_loudness_menu
        )
        normalize_checkbox.grid(row=0, column=0)
        self.loudness_menu = ctk.CTkOptionMenu(
            inputs, variable=self.loudness_preset_var, values=list(LOUDNESS_PRESETS), width=360
        )
        self.loudness_menu.grid(row=0, column=1, padx=(10, 0))
        lock.add(normalize_checkbox, self.loudness_menu)
        # After rendering, the preset menu depends on the "Normalize" checkbox again
        lock.on_unlock(self._update_loudness_menu)
        self._update_loudness_menu()
        self.next_row = row + 4

    def _quality_mode_name(self, mode):
        # Name of the mode in the menu: constant quality is a QP on video cards
        return QUALITY_GPU_QP if mode == QUALITY_CRF and self.gpu_encoder is not None else mode

    def _select_quality_mode(self, name):
        self.video_quality_var.set(QUALITY_CRF if name == QUALITY_GPU_QP else name)
        self._update_quality_fields()

    def _update_quality_fields(self):
        # Show the CRF field for constant quality (the QP field when a video card encodes),
        # otherwise the bitrate field, which shows "original" in the "Same bitrate as original" mode
        mode = self.video_quality_var.get()
        self.quality_menu.configure(values=[self._quality_mode_name(m) for m in VIDEO_QUALITY_MODES])
        self.quality_menu.set(self._quality_mode_name(mode))
        if mode == QUALITY_CRF and self.gpu_encoder is not None:
            label, shown = "Quality (QP):", self.gpu_qp_row
        elif mode == QUALITY_CRF:
            label, shown = "Quality (CRF):", self.crf_row
        else:
            label, shown = "Video bitrate:", self.bitrate_row
            self.original_bitrate_var.set(mode == QUALITY_ORIGINAL_BITRATE)
            self.bitrate_field.update()
        self.quality_value_label.configure(text=label)
        for row in (self.crf_row, self.gpu_qp_row, self.bitrate_row):
            if row is shown:
                row.grid()
            else:
                row.grid_remove()

    def check_gpu(self):
        # Show which encoder the chosen codec will use; when "Use GPU" is on,
        # make sure a video card encoder actually works. The checks are cached
        codec = self.codec_var.get()
        # Show the message before the checks, which can take a few seconds
        self.set_status("Checking the encoders…")
        self.frame.update_idletasks()

        cpu_encoder = find_cpu_encoder(codec)
        cpu_status = f"CPU encoder: {cpu_encoder[1]}" if cpu_encoder else f"No {codec} encoder found"
        if not self.use_gpu_var.get():
            self.set_status(cpu_status)
            self._set_gpu_encoder(None)
            return

        gpu_encoder = find_gpu_encoder(codec)
        self._set_gpu_encoder(gpu_encoder[1] if gpu_encoder is not None else None)
        if gpu_encoder is not None:
            self.set_status(f"Video card encoder: {gpu_encoder[1]}")
        elif any(find_gpu_encoder(other) for other in VIDEO_CODECS if other != codec):
            # The video card works, just not with this codec: keep "Use GPU" for the other codecs
            self.set_status(f"The video card can't encode this codec, so the CPU is used. {cpu_status}")
        else:
            self.use_gpu_var.set(False)
            self.set_status(cpu_status)
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

    def variables(self):
        return [self.codec_var, self.use_gpu_var, self.video_quality_var, self.crf_var, self.bitrate_var,
                self.gpu_qp_var, self.gpu_qp_encoder_var, self.normalize_audio_var, self.loudness_preset_var]

    def settings(self):
        return {
            "video_quality": self.video_quality_var.get(),
            "crf": self.crf_var.get(),
            "gpu_qp": self.gpu_qp_var.get(),
            "gpu_qp_encoder": self.gpu_qp_encoder_var.get(),
            "bitrate_kbps": self.bitrate_var.get(),
            "normalize_audio": self.normalize_audio_var.get(),
            "loudness_preset": self.loudness_preset_var.get(),
            "video_codec": self.codec_var.get(),
            "use_gpu": self.use_gpu_var.get(),
        }

    def parse(self):
        # Returns the encoding settings for main(), or raises InvalidInput.
        # Video quality: a CRF, or a bitrate (None keeps the bitrate of each original video)
        mode = self.video_quality_var.get()
        crf = qp = bitrate_kbps = None
        if mode == QUALITY_CRF:
            # The CRF is also needed with a video card: the CPU takes over the videos it can't encode
            crf = parse_field(self.crf_var.get(), "Quality (CRF)", MAX_CRF)
            if self.gpu_encoder is not None:
                qp = parse_field(self.gpu_qp_var.get(), "Quality (QP)", self.gpu_qp_max)
        elif mode == QUALITY_CUSTOM_BITRATE:
            bitrate_kbps = parse_field(self.bitrate_var.get(), "Video bitrate", MAX_BITRATE_KBPS)
        return {
            "crf": crf,
            "qp": qp,
            "bitrate_kbps": bitrate_kbps,
            # Loudness to normalize the audio to; None keeps the original audio
            "target_lufs": LOUDNESS_PRESETS[self.loudness_preset_var.get()] if self.normalize_audio_var.get() else None,
            "use_gpu": self.use_gpu_var.get(),
            "codec": self.codec_var.get(),
        }
