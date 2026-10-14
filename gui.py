import json
import os
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from main import main


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


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Watermark")
        self.root.resizable(True, False)

        # Restore the paths from the previous run, falling back to defaults
        settings = load_settings()
        self.raw_videos_var = ctk.StringVar(value=settings.get("raw_videos_path", "raw_videos"))
        self.output_folder_var = ctk.StringVar(value=settings.get("output_folder_path", "watermarked_videos"))
        self.watermark_image_var = ctk.StringVar(value=settings.get("watermark_image_path", "watermark.png"))

        # Save the paths whenever any of them changes
        for var in (self.raw_videos_var, self.output_folder_var, self.watermark_image_var):
            var.trace_add("write", self._save_paths)

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

        self.run_button = ctk.CTkButton(frame, text="Run", command=self._run)
        self.run_button.grid(row=3, column=0, columnspan=3, pady=(10, 5))

        # Progress of the video currently being rendered
        ctk.CTkLabel(frame, text="Current video:").grid(row=4, column=0, sticky="w", padx=10, pady=2)
        self.video_progress = ctk.CTkProgressBar(frame, mode="determinate")
        self._set_bar(self.video_progress, 0)
        self.video_progress.grid(row=4, column=1, sticky="ew", padx=5, pady=2)
        ctk.CTkLabel(frame, textvariable=self.video_percent_var).grid(row=4, column=2, sticky="w", padx=10, pady=2)

        # Progress over all videos
        ctk.CTkLabel(frame, text="Overall progress:").grid(row=5, column=0, sticky="w", padx=10, pady=2)
        self.progress = ctk.CTkProgressBar(frame, mode="determinate")
        self._set_bar(self.progress, 0)
        self.progress.grid(row=5, column=1, sticky="ew", padx=5, pady=2)
        ctk.CTkLabel(frame, textvariable=self.counts_var).grid(row=5, column=2, sticky="w", padx=10, pady=2)

        ctk.CTkLabel(frame, textvariable=self.status_var).grid(row=6, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 10))

    def _save_paths(self, *args):
        save_settings({
            "raw_videos_path": self.raw_videos_var.get(),
            "output_folder_path": self.output_folder_var.get(),
            "watermark_image_path": self.watermark_image_var.get(),
        })

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

        self.run_button.configure(state="disabled")
        self._set_bar(self.progress, 0)
        self._set_bar(self.video_progress, 0)
        self.video_percent_var.set("0%")
        self.counts_var.set("Processed: 0 / 0")
        self.status_var.set("Starting…")

        # Render in a background thread so the window doesn't freeze
        thread = threading.Thread(
            target=self._process,
            args=(raw_videos_path, output_folder_path, watermark_image_path),
            daemon=True
        )
        thread.start()

    def _process(self, raw_videos_path, output_folder_path, watermark_image_path):
        try:
            main(
                raw_videos_path,
                output_folder_path,
                watermark_image_path,
                on_progress=self._on_progress,
                on_video_progress=self._on_video_progress
            )
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
            self.status_var.set(f"Processing video {processed + 1} of {total}: {video_file}")

    def _on_video_progress(self, percent):
        # Called from the worker thread, so hand the UI update to the main thread
        self.root.after(0, self._update_video_progress, percent)

    def _update_video_progress(self, percent):
        self._set_bar(self.video_progress, percent / 100)
        self.video_percent_var.set(f"{percent}%")

    def _on_done(self):
        self.status_var.set("Done")
        self.run_button.configure(state="normal")
        messagebox.showinfo("Done", "All videos have been processed.")

    def _on_error(self, error):
        self.status_var.set("Error")
        self.run_button.configure(state="normal")
        messagebox.showerror("Error", str(error))


if __name__ == "__main__":
    # Follow the system light/dark theme
    ctk.set_appearance_mode("system")

    root = ctk.CTk()
    WatermarkApp(root)
    root.mainloop()
