from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton

from constants import VIDEO_STAGE_PLACEHOLDER
from ui.fields import set_secondary

# Progress bars count in tenths of a percent, so they move smoothly
PROGRESS_STEPS = 1000


def make_progress_bar():
    bar = QProgressBar()
    bar.setRange(0, PROGRESS_STEPS)
    bar.setTextVisible(False)
    return bar


class ControlPanel(QFrame):
    """
    Run, Pause and Stop buttons, the progress of the current video with its stage,
    the progress over all videos and the status line. Stays in view below the settings.
    """

    def __init__(self, on_run, on_pause, on_stop):
        super().__init__()
        self.setObjectName("card")
        layout = QGridLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(4)
        layout.setColumnStretch(1, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.run_button = QPushButton("Run")
        # Styled as the main button of the window
        self.run_button.setObjectName("primary")
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        for button, command in ((self.run_button, on_run), (self.pause_button, on_pause), (self.stop_button, on_stop)):
            button.setMinimumWidth(100)
            button.clicked.connect(command)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons, 0, 0, 1, 3)
        layout.setRowMinimumHeight(1, 6)

        # Progress of the video currently being rendered
        layout.addWidget(QLabel("Current video:"), 2, 0)
        self.video_progress = make_progress_bar()
        layout.addWidget(self.video_progress, 2, 1)
        self.video_percent_label = QLabel()
        self.video_percent_label.setMinimumWidth(40)
        layout.addWidget(self.video_percent_label, 2, 2)
        # Stage the current video bar shows the progress of, e.g. "[1/3] Measuring loudness"
        self.video_stage_label = QLabel()
        layout.addWidget(self.video_stage_label, 3, 1)

        # Progress over all videos
        layout.addWidget(QLabel("Overall progress:"), 4, 0)
        self.progress = make_progress_bar()
        layout.addWidget(self.progress, 4, 1)

        self.status_label = QLabel("Ready")
        layout.setRowMinimumHeight(5, 6)
        layout.addWidget(self.status_label, 6, 0, 1, 3)

        self.set_running(False)
        self.reset_video_progress()

    def set_status(self, text):
        self.status_label.setText(text)

    def set_video_stage(self, stage):
        # Show the stage of the current video, or a gray placeholder (stage None) while no video is processed
        if stage is None:
            set_secondary(self.video_stage_label)
            self.video_stage_label.setText(VIDEO_STAGE_PLACEHOLDER)
        else:
            self.video_stage_label.setForegroundRole(QPalette.ColorRole.WindowText)
            self.video_stage_label.setText(stage)

    def set_video_progress(self, stage, percent):
        self.video_progress.setValue(round(percent / 100 * PROGRESS_STEPS))
        self.video_percent_label.setText(f"{percent}%")
        self.set_video_stage(stage)

    def reset_video_progress(self):
        self.set_video_progress(None, 0)

    def set_overall_progress(self, fraction):
        self.progress.setValue(round(fraction * PROGRESS_STEPS))

    def set_running(self, running):
        # Run while idle; Pause and Stop while rendering
        self.run_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.pause_button.setText("Pause")
        self.stop_button.setEnabled(running)

    def set_paused(self, paused):
        self.pause_button.setText("Resume" if paused else "Pause")

    def set_stopping(self):
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
