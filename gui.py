import json
import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

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
    # Empty is allowed while typing; otherwise a whole number from 1 to 100
    if value == "":
        return True
    return value.isascii() and value.isdigit() and not value.startswith("0") and int(value) <= 100


def valid_percent_or(value, default):
    # Use a saved percentage only if it is still a valid whole number
    value = str(value) if value is not None else ""
    return value if value != "" and is_percent_input(value) else default


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

        # Save the settings whenever any of them changes
        for var in (self.raw_videos_var, self.output_folder_var, self.watermark_image_var,
                    self.width_var, self.height_var, self.keep_ratio_var):
            var.trace_add("write", self._save_settings)

        self.status_var = ctk.StringVar(value="Ready")
        self.video_percent_var = ctk.StringVar(value="0%")
        self.counts_var = ctk.StringVar(value="Processed: 0 / 0")

        frame = ctk.CTkFrame(root)
        frame.grid(sticky="nsew", padx=10, pady=10)
        root.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self._add_path_row(frame, 0, "Raw videos folder:", self.raw_videos_var, self._browse_raw_videos)
        self._add_path_row(frame, 1, "Output folder:", self.output_folder_var, self._browse_output_folder)
        self._add_path_row(frame, 2, "Watermark image:", self.watermark_image_var, self._browse_watermark)

        # Watermark width as a percentage of the video width
        ctk.CTkLabel(frame, text="Watermark width:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        width_row = ctk.CTkFrame(frame, fg_color="transparent")
        width_row.grid(row=3, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        # Allow typing only whole numbers from 1 to 100
        validate_percent = (root.register(is_percent_input), "%P")
        ctk.CTkEntry(
            width_row,
            textvariable=self.width_var,
            width=70,
            validate="key",
            validatecommand=validate_percent
        ).grid(row=0, column=0)
        ctk.CTkLabel(width_row, text="% of video width").grid(row=0, column=1, padx=(5, 0))

        # Watermark height: derived from the width, or a custom percentage of the video height
        ctk.CTkLabel(frame, text="Watermark height:").grid(row=4, column=0, sticky="w", padx=10, pady=2)
        height_row = ctk.CTkFrame(frame, fg_color="transparent")
        height_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=2)
        self.height_entry = ctk.CTkEntry(
            height_row,
            textvariable=self.height_var,
            width=70,
            validate="key",
            validatecommand=validate_percent
        )
        self.height_entry.grid(row=0, column=0)
        self.height_entry_text_color = self.height_entry.cget("text_color")
        ctk.CTkLabel(height_row, text="% of video height").grid(row=0, column=1, padx=(5, 0))
        ctk.CTkCheckBox(
            height_row,
            text="Keep aspect ratio",
            variable=self.keep_ratio_var,
            command=self._update_height_entry
        ).grid(row=0, column=2, padx=(20, 0))
        self._update_height_entry()

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=5, column=0, columnspan=3, pady=(10, 5))
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
        ctk.CTkLabel(frame, text="Current video:").grid(row=6, column=0, sticky="w", padx=10, pady=2)
        self.video_progress = ctk.CTkProgressBar(frame, mode="determinate")
        self._set_bar(self.video_progress, 0)
        self.video_progress.grid(row=6, column=1, sticky="ew", padx=5, pady=2)
        ctk.CTkLabel(frame, textvariable=self.video_percent_var).grid(row=6, column=2, sticky="w", padx=10, pady=2)

        # Progress over all videos
        ctk.CTkLabel(frame, text="Overall progress:").grid(row=7, column=0, sticky="w", padx=10, pady=2)
        self.progress = ctk.CTkProgressBar(frame, mode="determinate")
        self._set_bar(self.progress, 0)
        self.progress.grid(row=7, column=1, sticky="ew", padx=5, pady=2)
        ctk.CTkLabel(frame, textvariable=self.counts_var).grid(row=7, column=2, sticky="w", padx=10, pady=2)

        ctk.CTkLabel(frame, textvariable=self.status_var).grid(row=8, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 10))

    def _save_settings(self, *args):
        save_settings({
            "raw_videos_path": self.raw_videos_var.get(),
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": self.watermark_image_var.get(),
            "width_percent": self.width_var.get(),
            "height_percent": self.height_var.get(),
            "keep_aspect_ratio": self.keep_ratio_var.get(),
        })

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
                text_color=("gray55", "gray50")
            )
        else:
            self.height_entry.configure(
                state="normal",
                textvariable=self.height_var,
                text_color=self.height_entry_text_color
            )
        self.height_entry.configure(validate="key")

    def _parse_percent(self, value, name):
        # Returns the percentage as a number, or None after showing an error
        if not is_percent_input(value) or value == "":
            messagebox.showerror("Error", f"{name} must be a whole number from 1 to 100.")
            return None
        return int(value)

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
        ctk.CTkEntry(frame, textvariable=variable, width=350).grid(row=row, column=1, sticky="ew", padx=5, pady=(10 if row == 0 else 2, 2))
        ctk.CTkButton(frame, text="Browse…", width=90, command=browse_command).grid(row=row, column=2, padx=10, pady=(10 if row == 0 else 2, 2))

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

        self.control = RenderControl()
        self.paused = False
        self.processing_status = "Starting…"
        self.run_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="Pause")
        self.stop_button.configure(state="normal")
        self._set_bar(self.progress, 0)
        self._set_bar(self.video_progress, 0)
        self.video_percent_var.set("0%")
        self.counts_var.set("Processed: 0 / 0")
        self.status_var.set("Starting…")

        # Render in a background thread so the window doesn't freeze
        thread = threading.Thread(
            target=self._process,
            args=(raw_videos_path, output_folder_path, watermark_image_path, self.control, width_percent, height_percent),
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
        self.pause_button.configure(state="disabled", text="Pause")
        self.stop_button.configure(state="disabled")

    def _process(self, raw_videos_path, output_folder_path, watermark_image_path, control, width_percent, height_percent):
        try:
            main(
                raw_videos_path,
                output_folder_path,
                watermark_image_path,
                on_progress=self._on_progress,
                on_video_progress=self._on_video_progress,
                control=control,
                width_percent=width_percent,
                height_percent=height_percent
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
        self.counts_var.set(f"Processed: {processed} / {total}")

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
