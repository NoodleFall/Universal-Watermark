import threading
from tkinter import messagebox

import customtkinter as ctk

from constants import APP_NAME, MAX_WINDOW_SCREEN_SHARE, MIN_SETTINGS_HEIGHT
from functions.render_control import RenderCancelled, RenderControl
from main import main
from ui.control_panel import ControlPanel
from ui.fields import InputLock
from ui.motion import MotionSection
from ui.number_input import InvalidInput
from ui.sections import EncodingSection, PathsSection, WatermarkLookSection
from ui.settings import load_settings, save_settings


class UniversalWatermark:
    """
    The main window: the settings in sections, which scroll when the window is too short
    for them, and the control panel below them. Renders the videos in a background thread.
    """

    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.resizable(True, True)

        # Pause/stop control of the current rendering, None when idle
        self.control = None
        self.paused = False
        # Status to restore after resuming from pause
        self.processing_status = ""
        # Closing the window while rendering works like Stop
        self.closing = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Settings scroll when the window is too short for them; the control panel below stays in view
        settings_frame = ctk.CTkScrollableFrame(root)
        settings_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 0))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)

        self.panel = ControlPanel(root, on_run=self._run, on_pause=self._toggle_pause, on_stop=self._stop)
        self.panel.grid(row=1, column=0, sticky="ew", padx=10, pady=10)

        # Restore the settings from the previous run, falling back to defaults
        saved = load_settings()
        self.lock = InputLock()
        self.paths = PathsSection(settings_frame, 0, self.lock, saved)
        self.look = WatermarkLookSection(settings_frame, self.paths.next_row, self.lock, saved)
        self.motion = MotionSection(settings_frame, self.look.next_row, self.lock, saved)
        self.encoding = EncodingSection(settings_frame, self.motion.next_row, self.lock, saved, self.panel.set_status)
        self.sections = (self.paths, self.look, self.motion, self.encoding)

        # Save the settings whenever any of them changes
        for section in self.sections:
            for var in section.variables():
                var.trace_add("write", self._save_settings)

        # Find the video card encoder right away if "Use GPU" was on last time, to show its QP field
        if self.encoding.use_gpu_var.get():
            self.encoding.check_gpu()

        self._fit_window(settings_frame)

    def _fit_window(self, settings_frame):
        # Open the window tall enough for all the settings, unless the screen is too short for that.
        # customtkinter sizes are set in unscaled units, while Tk reports scaled pixels
        self.root.update_idletasks()
        panel_height = self.panel.winfo_reqheight()
        max_height = self.root.winfo_screenheight() * MAX_WINDOW_SCREEN_SHARE - panel_height
        settings_frame.configure(
            width=settings_frame._reverse_widget_scaling(settings_frame.winfo_reqwidth()),
            height=settings_frame._reverse_widget_scaling(min(settings_frame.winfo_reqheight(), max_height))
        )
        # The window can be made shorter, down to a few rows of settings
        self.root.update_idletasks()
        self.root.minsize(
            self.root._reverse_window_scaling(self.root.winfo_reqwidth()),
            self.root._reverse_window_scaling(panel_height) + MIN_SETTINGS_HEIGHT
        )

    def _save_settings(self, *args):
        settings = {}
        for section in self.sections:
            settings.update(section.settings())
        save_settings(settings)

    def _run(self):
        # Check all the settings before starting; the first wrong one is shown in an error message
        try:
            paths = self.paths.parse()
            look = self.look.parse()
            motions, random_motion_order = self.motion.parse()
            encoding = self.encoding.parse()
        except InvalidInput as e:
            messagebox.showerror("Error", str(e))
            return

        self.control = RenderControl()
        self.paused = False
        self.processing_status = "Starting…"
        self.lock.set_enabled(False)
        self.panel.set_running(True)
        self.panel.set_overall_progress(0)
        self.panel.reset_video_progress()
        self.panel.set_status("Starting…")

        # Render in a background thread so the window doesn't freeze
        thread = threading.Thread(
            target=self._process,
            args=(self.control, {
                **paths, **look, **encoding, "motions": motions, "random_motion_order": random_motion_order
            }),
            daemon=True
        )
        thread.start()

    def _toggle_pause(self):
        if self.paused:
            self.control.resume()
            self.panel.set_status(self.processing_status)
        else:
            self.control.pause()
            self.panel.set_status("Paused")
        self.paused = not self.paused
        self.panel.set_paused(self.paused)

    def _stop(self):
        self.control.stop()
        self.panel.set_stopping()
        self.panel.set_status("Stopping…")

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
        # Return to the idle state
        self.control = None
        self.paused = False
        self.lock.set_enabled(True)
        self.panel.set_running(False)
        self.panel.set_video_stage(None)

    def _process(self, control, settings):
        # Runs in the background thread; the results go to the main thread
        try:
            main(
                on_progress=self._on_progress,
                on_video_progress=self._on_video_progress,
                control=control,
                **settings
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
        self.panel.set_overall_progress(processed / max(total, 1))
        if video_file is not None:
            self.panel.reset_video_progress()
            self.processing_status = f"Processing video {processed + 1} of {total}: {video_file}"
            self.panel.set_status(self.processing_status)

    def _on_video_progress(self, stage, percent):
        # Called from the worker thread, so hand the UI update to the main thread
        self.root.after(0, self.panel.set_video_progress, stage, percent)

    def _on_done(self):
        if self._close_if_requested():
            return
        self.panel.set_status("Done")
        self._finish()
        messagebox.showinfo("Done", "All videos have been processed.")

    def _on_cancelled(self):
        if self._close_if_requested():
            return
        self.panel.set_status("Stopped")
        self.panel.reset_video_progress()
        self._finish()

    def _on_error(self, error):
        if self._close_if_requested():
            print(f"Error: {error}")
            return
        self.panel.set_status("Error")
        self._finish()
        messagebox.showerror("Error", str(error))


def run():
    # Follow the system light/dark theme
    ctk.set_appearance_mode("system")

    root = ctk.CTk()
    UniversalWatermark(root)
    root.mainloop()
