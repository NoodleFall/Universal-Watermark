import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from main import main


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Watermark")
        self.root.resizable(True, False)

        self.raw_videos_var = tk.StringVar(value="raw_videos")
        self.output_folder_var = tk.StringVar(value="watermarked_videos")
        self.watermark_image_var = tk.StringVar(value="watermark.png")
        self.status_var = tk.StringVar(value="Ready")
        self.video_percent_var = tk.StringVar(value="0%")
        self.counts_var = tk.StringVar(value="Processed: 0 / 0")

        frame = ttk.Frame(root, padding=10)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        self._add_path_row(frame, 0, "Raw videos folder:", self.raw_videos_var, self._browse_raw_videos)
        self._add_path_row(frame, 1, "Output folder:", self.output_folder_var, self._browse_output_folder)
        self._add_path_row(frame, 2, "Watermark image:", self.watermark_image_var, self._browse_watermark)

        self.run_button = ttk.Button(frame, text="Run", command=self._run)
        self.run_button.grid(row=3, column=0, columnspan=3, pady=(10, 5))

        # Progress of the video currently being rendered
        ttk.Label(frame, text="Current video:").grid(row=4, column=0, sticky="w", pady=2)
        self.video_progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.video_progress.grid(row=4, column=1, sticky="ew", padx=5, pady=2)
        ttk.Label(frame, textvariable=self.video_percent_var).grid(row=4, column=2, sticky="w", pady=2)

        # Progress over all videos
        ttk.Label(frame, text="Overall progress:").grid(row=5, column=0, sticky="w", pady=2)
        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.grid(row=5, column=1, sticky="ew", padx=5, pady=2)
        ttk.Label(frame, textvariable=self.counts_var).grid(row=5, column=2, sticky="w", pady=2)

        ttk.Label(frame, textvariable=self.status_var).grid(row=6, column=0, columnspan=3, sticky="w", pady=(5, 0))

    def _add_path_row(self, frame, row, label, variable, browse_command):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(frame, textvariable=variable, width=50).grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        ttk.Button(frame, text="Browse…", command=browse_command).grid(row=row, column=2, pady=2)

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

        self.run_button.config(state="disabled")
        self.progress["value"] = 0
        self.video_progress["value"] = 0
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
        # Avoid a zero maximum when the folder has no videos
        self.progress["maximum"] = max(total, 1)
        self.progress["value"] = processed
        self.counts_var.set(f"Processed: {processed} / {total}")

        if video_file is not None:
            self.video_progress["value"] = 0
            self.video_percent_var.set("0%")
            self.status_var.set(f"Processing video {processed + 1} of {total}: {video_file}")

    def _on_video_progress(self, percent):
        # Called from the worker thread, so hand the UI update to the main thread
        self.root.after(0, self._update_video_progress, percent)

    def _update_video_progress(self, percent):
        self.video_progress["value"] = percent
        self.video_percent_var.set(f"{percent}%")

    def _on_done(self):
        self.status_var.set("Done")
        self.run_button.config(state="normal")
        messagebox.showinfo("Done", "All videos have been processed.")

    def _on_error(self, error):
        self.status_var.set("Error")
        self.run_button.config(state="normal")
        messagebox.showerror("Error", str(error))


if __name__ == "__main__":
    root = tk.Tk()
    WatermarkApp(root)
    root.mainloop()
