import customtkinter as ctk

from constants import DISABLED_TEXT_COLOR, VIDEO_STAGE_PLACEHOLDER


def set_bar(bar, value):
    # customtkinter still draws a small rounded stub at 0,
    # so hide it by painting the progress part with the background color
    if not hasattr(bar, "default_progress_color"):
        bar.default_progress_color = bar.cget("progress_color")
    progress_color = bar.cget("fg_color") if value <= 0 else bar.default_progress_color
    bar.configure(progress_color=progress_color)
    bar.set(value)


class ControlPanel(ctk.CTkFrame):
    """
    Run, Pause and Stop buttons, the progress of the current video with its stage,
    the progress over all videos and the status line. Stays in view below the settings.
    """

    def __init__(self, master, on_run, on_pause, on_stop):
        super().__init__(master)
        self.columnconfigure(1, weight=1)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.grid(row=0, column=0, columnspan=3, pady=(10, 5))
        self.run_button = ctk.CTkButton(buttons, text="Run", width=100, command=on_run)
        self.run_button.grid(row=0, column=0, padx=5)
        self.pause_button = ctk.CTkButton(buttons, text="Pause", width=100, state="disabled", command=on_pause)
        self.pause_button.grid(row=0, column=1, padx=5)
        self.stop_button = ctk.CTkButton(buttons, text="Stop", width=100, state="disabled", command=on_stop)
        self.stop_button.grid(row=0, column=2, padx=5)

        # Progress of the video currently being rendered
        ctk.CTkLabel(self, text="Current video:").grid(row=1, column=0, sticky="w", padx=10, pady=2)
        self.video_progress = ctk.CTkProgressBar(self, mode="determinate")
        self.video_progress.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.video_percent_var = ctk.StringVar(value="0%")
        ctk.CTkLabel(self, textvariable=self.video_percent_var).grid(row=1, column=2, sticky="w", padx=10, pady=2)
        # Stage the current video bar shows the progress of, e.g. "[1/3] Measuring loudness"
        self.video_stage_label = ctk.CTkLabel(self)
        self.video_stage_label.grid(row=2, column=1, sticky="w", padx=5, pady=(0, 2))
        self.default_text_color = self.video_stage_label.cget("text_color")
        self.reset_video_progress()

        # Progress over all videos
        ctk.CTkLabel(self, text="Overall progress:").grid(row=3, column=0, sticky="w", padx=10, pady=2)
        self.progress = ctk.CTkProgressBar(self, mode="determinate")
        set_bar(self.progress, 0)
        self.progress.grid(row=3, column=1, sticky="ew", padx=5, pady=2)

        self.status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(self, textvariable=self.status_var).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=10, pady=(5, 10)
        )

    def set_status(self, text):
        self.status_var.set(text)

    def set_video_stage(self, stage):
        # Show the stage of the current video, or a gray placeholder (stage None) while no video is processed
        if stage is None:
            self.video_stage_label.configure(text=VIDEO_STAGE_PLACEHOLDER, text_color=DISABLED_TEXT_COLOR)
        else:
            self.video_stage_label.configure(text=stage, text_color=self.default_text_color)

    def set_video_progress(self, stage, percent):
        set_bar(self.video_progress, percent / 100)
        self.video_percent_var.set(f"{percent}%")
        self.set_video_stage(stage)

    def reset_video_progress(self):
        set_bar(self.video_progress, 0)
        self.video_percent_var.set("0%")
        self.set_video_stage(None)

    def set_overall_progress(self, fraction):
        set_bar(self.progress, fraction)

    def set_running(self, running):
        # Run while idle; Pause and Stop while rendering
        self.run_button.configure(state="disabled" if running else "normal")
        self.pause_button.configure(state="normal" if running else "disabled", text="Pause")
        self.stop_button.configure(state="normal" if running else "disabled")

    def set_paused(self, paused):
        self.pause_button.configure(text="Resume" if paused else "Pause")

    def set_stopping(self):
        self.pause_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
