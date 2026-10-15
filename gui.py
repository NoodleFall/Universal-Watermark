import json
import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from constants import DISABLED_TEXT_COLOR, MAX_PERCENT, PERCENT_INPUT_RE, PERCENT_STEP
from main import RenderCancelled, RenderControl, main


def get_settings_path():
    # %APPDATA% on Windows, ~/.config (or $XDG_CONFIG_HOME) elsewhere
    config_dir = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_dir, "watermark", "settings.json")


def load_settings():
    try:
        with open(get_settings_path(), encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        # No saved settings yet, or the file is broken
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings):
    settings_path = get_settings_path()
    try:
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"Failed to save settings: {e}")


def is_percent_input(value):
    if not PERCENT_INPUT_RE.fullmatch(value):
        return False
    number = parse_percent(value)
    return number is None or number <= MAX_PERCENT


def parse_percent(value):
    # Returns the percentage as a number, or None if it isn't a number yet
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def format_percent(number):
    # 50.0 -> "50", 12.50 -> "12.5"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def valid_percent_or(value, default):
    # Use a saved percentage only if it is still valid
    value = str(value) if value is not None else ""
    number = parse_percent(value)
    return value if is_percent_input(value) and number is not None and number > 0 else default


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Watermark")
        self.root.resizable(True, False)

        # Restore the settings from the previous run, falling back to defaults
        settings = load_settings()
        self.raw_videos_var = ctk.StringVar(value=settings.get("raw_videos_path", "raw_videos"))
        self.output_folder_var = ctk.StringVar(value=settings.get("output_folder_path", "watermarked_videos"))
        self.watermark_image_var = ctk.StringVar(value=settings.get("watermark_image_path", "watermark.png"))
        self.width_var = ctk.StringVar(value=valid_percent_or(settings.get("width_percent"), "50"))
        self.height_var = ctk.StringVar(value=valid_percent_or(settings.get("height_percent"), "20"))
        # Shown in the height field while the aspect ratio is kept
        self.auto_height_var = ctk.StringVar(value="auto")
        self.keep_ratio_var = ctk.BooleanVar(value=bool(settings.get("keep_aspect_ratio", True)))
        self.opacity_var = ctk.StringVar(value=valid_percent_or(settings.get("opacity_percent"), "33"))

        # Save the settings whenever any of them changes
        for var in (self.raw_videos_var, self.output_folder_var, self.watermark_image_var,
                    self.width_var, self.height_var, self.keep_ratio_var, self.opacity_var):
            var.trace_add("write", self._save_settings)

        self.status_var = ctk.StringVar(value="Ready")
        self.video_percent_var = ctk.StringVar(value="0%")

        frame = ctk.CTkFrame(root)
        frame.grid(sticky="nsew", padx=10, pady=10)
        root.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        # Inputs that are locked while rendering
        self.input_entries = []
        self.input_buttons = []

        self._add_path_row(frame, 0, "Raw videos folder:", self.raw_videos_var, self._browse_raw_videos)
        self._add_path_row(frame, 1, "Output folder:", self.output_folder_var, self._browse_output_folder)
        self._add_path_row(frame, 2, "Watermark image:", self.watermark_image_var, self._browse_watermark)

        # Watermark width as a percentage of the video width
        ctk.CTkLabel(frame, text="Watermark width:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        width_row = ctk.CTkFrame(frame, fg_color="transparent")
        width_row.grid(row=3, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_percent_field(width_row, self.width_var)
        ctk.CTkLabel(width_row, text=f"% of video width (max: {MAX_PERCENT})").grid(row=0, column=2, padx=(5, 0))

        # Watermark height: derived from the width, or a custom percentage of the video height
        ctk.CTkLabel(frame, text="Watermark height:").grid(row=4, column=0, sticky="w", padx=10, pady=2)
        height_row = ctk.CTkFrame(frame, fg_color="transparent")
        height_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.height_entry, self.height_arrows = self._add_percent_field(height_row, self.height_var)
        self.height_entry_text_color = self.height_entry.cget("text_color")
        ctk.CTkLabel(height_row, text=f"% of video height (max: {MAX_PERCENT})").grid(row=0, column=2, padx=(5, 0))
        keep_ratio_checkbox = ctk.CTkCheckBox(
            height_row,
            text="Keep aspect ratio",
            variable=self.keep_ratio_var,
            command=self._update_height_entry
        )
        keep_ratio_checkbox.grid(row=0, column=3, padx=(20, 0))
        self.input_buttons.append(keep_ratio_checkbox)
        self._update_height_entry()

        # Watermark opacity: 100% is fully opaque
        ctk.CTkLabel(frame, text="Watermark opacity:").grid(row=5, column=0, sticky="w", padx=10, pady=2)
        opacity_row = ctk.CTkFrame(frame, fg_color="transparent")
        opacity_row.grid(row=5, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self._add_percent_field(opacity_row, self.opacity_var)
        ctk.CTkLabel(opacity_row, text=f"% (max: {MAX_PERCENT})").grid(row=0, column=2, padx=(5, 0))

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=6, column=0, columnspan=3, pady=(10, 5))
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
        ctk.CTkLabel(frame, text="Current video:").grid(row=7, column=0, sticky="w", padx=10, pady=2)
        self.video_progress = ctk.CTkProgressBar(frame, mode="determinate")
        self._set_bar(self.video_progress, 0)
        self.video_progress.grid(row=7, column=1, sticky="ew", padx=5, pady=2)
        ctk.CTkLabel(frame, textvariable=self.video_percent_var).grid(row=7, column=2, sticky="w", padx=10, pady=2)

        # Progress over all videos
        ctk.CTkLabel(frame, text="Overall progress:").grid(row=8, column=0, sticky="w", padx=10, pady=2)
        self.progress = ctk.CTkProgressBar(frame, mode="determinate")
        self._set_bar(self.progress, 0)
        self.progress.grid(row=8, column=1, sticky="ew", padx=5, pady=2)

        ctk.CTkLabel(frame, textvariable=self.status_var).grid(row=9, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 10))

    def _save_settings(self, *args):
        save_settings({
            "raw_videos_path": self.raw_videos_var.get(),
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": self.watermark_image_var.get(),
            "width_percent": self.width_var.get(),
            "height_percent": self.height_var.get(),
            "keep_aspect_ratio": self.keep_ratio_var.get(),
            "opacity_percent": self.opacity_var.get(),
        })

    def _add_percent_field(self, parent, variable):
        # Entry for a percentage with ▲/▼ buttons; returns the entry and the buttons
        entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            width=70,
            validate="key",
            validatecommand=(self.root.register(lambda value: self._validate_percent(variable, value)), "%P")
        )
        entry.grid(row=0, column=0)

        arrows = ctk.CTkFrame(parent, fg_color="transparent")
        arrows.grid(row=0, column=1, padx=(3, 0))
        up = ctk.CTkButton(arrows, text="▲", width=22, height=13, font=("", 8),
                           command=lambda: self._step_percent(entry, variable, 1))
        up.grid(row=0, column=0, pady=(0, 1))
        down = ctk.CTkButton(arrows, text="▼", width=22, height=13, font=("", 8),
                             command=lambda: self._step_percent(entry, variable, -1))
        down.grid(row=1, column=0)

        # Up/Down keys and the mouse wheel change the value too
        entry.bind("<Up>", lambda e: self._step_percent(entry, variable, 1))
        entry.bind("<Down>", lambda e: self._step_percent(entry, variable, -1))
        entry.bind("<MouseWheel>", lambda e: self._step_percent(entry, variable, 1 if e.delta > 0 else -1))
        entry.bind("<Button-4>", lambda e: self._step_percent(entry, variable, 1))
        entry.bind("<Button-5>", lambda e: self._step_percent(entry, variable, -1))

        self.input_entries.append(entry)
        self.input_buttons.extend((up, down))
        return entry, (up, down)

    def _validate_percent(self, variable, value):
        if not PERCENT_INPUT_RE.fullmatch(value):
            return False
        number = parse_percent(value)
        if number is not None and number > MAX_PERCENT:
            # Too large: reset the field to the maximum. Changing the variable inside
            # the validation would turn validation off, so do it right after
            self.root.after_idle(variable.set, format_percent(MAX_PERCENT))
            return False
        return True

    def _step_percent(self, entry, variable, direction):
        if entry.cget("state") == "disabled":
            return
        current = parse_percent(variable.get()) or 0
        new = round(current + direction * PERCENT_STEP, 2)
        # Stay within (0, 100]: going below zero keeps the current value
        if new <= 0:
            return
        variable.set(format_percent(min(new, MAX_PERCENT)))

    def _update_height_entry(self):
        # The custom height is only used when the aspect ratio is not kept.
        # A disabled CTkEntry looks the same as an enabled one,
        # so also show "auto" in gray instead of the custom value.
        # Switching the variable runs the input validation on "auto", and Tk turns
        # validation off for good when it fails, so pause it during the switch
        self.height_entry.configure(validate="none")
        if self.keep_ratio_var.get():
            self.height_entry.configure(
                state="disabled",
                textvariable=self.auto_height_var,
                text_color=DISABLED_TEXT_COLOR
            )
        else:
            self.height_entry.configure(
                state="normal",
                textvariable=self.height_var,
                text_color=self.height_entry_text_color
            )
        self.height_entry.configure(validate="key")
        for arrow in self.height_arrows:
            arrow.configure(state="disabled" if self.keep_ratio_var.get() else "normal")

    def _parse_percent(self, value, name):
        # Returns the percentage as a number, or None after showing an error
        percent = parse_percent(value) if is_percent_input(value) else None
        if percent is None or percent <= 0:
            messagebox.showerror("Error", f"{name} must be a number greater than 0 and up to {MAX_PERCENT}.")
            return None
        return percent

    def _set_bar(self, bar, value):
        # customtkinter still draws a small rounded stub at 0,
        # so hide it by painting the progress part with the background color
        if not hasattr(bar, "default_progress_color"):
            bar.default_progress_color = bar.cget("progress_color")
        progress_color = bar.cget("fg_color") if value <= 0 else bar.default_progress_color
        bar.configure(progress_color=progress_color)
        bar.set(value)

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
        for entry in self.input_entries:
            if entry is self.height_entry:
                continue
            if not hasattr(entry, "default_text_color"):
                entry.default_text_color = entry.cget("text_color")
            entry.configure(state=state, text_color=entry.default_text_color if enabled else DISABLED_TEXT_COLOR)
        for button in self.input_buttons:
            if button in self.height_arrows:
                continue
            button.configure(state=state)

        # The height field also depends on the "Keep aspect ratio" checkbox
        if enabled:
            self._update_height_entry()
        else:
            self.height_entry.configure(state="disabled", text_color=DISABLED_TEXT_COLOR)
            for arrow in self.height_arrows:
                arrow.configure(state="disabled")

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
        width_percent = self._parse_percent(self.width_var.get(), "Watermark width")
        if width_percent is None:
            return
        if self.keep_ratio_var.get():
            height_percent = None
        else:
            height_percent = self._parse_percent(self.height_var.get(), "Watermark height")
            if height_percent is None:
                return

        # Validate the watermark opacity
        opacity_percent = self._parse_percent(self.opacity_var.get(), "Watermark opacity")
        if opacity_percent is None:
            return

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
        self.status_var.set("Starting…")

        # Render in a background thread so the window doesn't freeze
        thread = threading.Thread(
            target=self._process,
            args=(raw_videos_path, output_folder_path, watermark_image_path, self.control,
                  width_percent, height_percent, opacity_percent),
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

    def _process(self, raw_videos_path, output_folder_path, watermark_image_path, control,
                 width_percent, height_percent, opacity_percent):
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
                opacity_percent=opacity_percent
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
            # Remember the status to restore it after resuming from pause
            self.processing_status = f"Processing video {processed + 1} of {total}: {video_file}"
            self.status_var.set(self.processing_status)

    def _on_video_progress(self, percent):
        # Called from the worker thread, so hand the UI update to the main thread
        self.root.after(0, self._update_video_progress, percent)

    def _update_video_progress(self, percent):
        self._set_bar(self.video_progress, percent / 100)
        self.video_percent_var.set(f"{percent}%")

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


if __name__ == "__main__":
    # Follow the system light/dark theme
    ctk.set_appearance_mode("system")

    root = ctk.CTk()
    WatermarkApp(root)
    root.mainloop()
