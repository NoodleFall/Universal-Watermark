import sys
import threading

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from constants import APP_NAME, MAX_WINDOW_SCREEN_SHARE, MIN_SETTINGS_HEIGHT
from functions.render_control import RenderCancelled, RenderControl
from functions.batch import process_videos
from ui.control_panel import ControlPanel
from ui.fields import InputLock, make_title, set_secondary
from ui.history import History
from ui.motion import MotionSection
from ui.number_input import InvalidInput
from ui.sections import EncodingSection, PathsSection, WatermarkLookSection
from ui.settings import load_settings, save_settings
from ui.style import apply_style
from ui.videos import VideosPage, plural

UNDO_KEYS = [QKeySequence("Ctrl+Z")]
REDO_KEYS = [QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")]

# Space around and between the cards
WINDOW_MARGIN = 12
CARD_SPACING = 10
SCROLLBAR_GAP = 6


class RenderSignals(QObject):
    """
    Reports of the render thread. Signals emitted in that thread run the connected
    methods of the window in the main thread, where the window may be changed.
    """

    progress = Signal(int, int, object)
    video_progress = Signal(object, object)
    done = Signal()
    cancelled = Signal()
    error = Signal(object)


class UniversalWatermark(QMainWindow):
    """
    The main window, in two pages: first the videos to watermark, then the settings in cards,
    which scroll when the window is too short for them, and the control panel below them.
    Renders the videos in a background thread. Ctrl+Z undoes the changes on the shown page,
    Ctrl+Shift+Z and Ctrl+Y redo them: each page has its own history, so nothing changes out of sight.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)

        # Pause/stop control of the current rendering, None when idle
        self.control = None
        self.paused = False
        # Status to restore after resuming from pause
        self.processing_status = ""
        # Closing the window while rendering works like Stop
        self.closing = False

        self.signals = RenderSignals()
        self.signals.progress.connect(self._update_progress)
        self.signals.video_progress.connect(self._update_video_progress)
        self.signals.done.connect(self._on_done)
        self.signals.cancelled.connect(self._on_cancelled)
        self.signals.error.connect(self._on_error)

        self.panel = ControlPanel(on_run=self._run, on_pause=self._toggle_pause, on_stop=self._stop)

        # Restore the settings from the previous run, falling back to defaults
        saved = load_settings()
        self.lock = InputLock()
        # Undo history of each page: the videos, the settings
        self.histories = (History(), History())
        self.paths = PathsSection(self.lock, saved)
        self.look = WatermarkLookSection(self.lock, saved)
        self.motion = MotionSection(self.lock, saved)
        self.encoding = EncodingSection(self.lock, saved, self.panel.set_status)
        self.sections = (self.paths, self.look, self.motion, self.encoding)
        self.videos = VideosPage(self.histories[0], on_next=self._show_settings)
        self.videos.load_settings(saved)

        # Settings scroll when the window is too short for them; the control panel below stays in view
        self.settings_widget = QWidget()
        self.settings_widget.setObjectName("settings")
        settings_layout = QVBoxLayout(self.settings_widget)
        # A gap between the cards and the scroll bar
        settings_layout.setContentsMargins(0, 0, SCROLLBAR_GAP, 0)
        settings_layout.setSpacing(CARD_SPACING)
        for section in self.sections:
            settings_layout.addWidget(section.card)
        settings_layout.addStretch()
        self._align_setting_labels()

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.settings_widget)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Settings page: back to the videos, the settings and the control panel
        self.top_bar = QHBoxLayout()
        self.back_button = QPushButton("←  Back")
        self.back_button.clicked.connect(self._show_videos)
        self.lock.add(self.back_button)
        self.top_bar.addWidget(self.back_button)
        self.top_bar.addSpacing(6)
        self.top_bar.addWidget(make_title("Settings", 1.4))
        self.videos_count_label = QLabel()
        set_secondary(self.videos_count_label)
        self.top_bar.addSpacing(6)
        self.top_bar.addWidget(self.videos_count_label, 0, Qt.AlignmentFlag.AlignBottom)
        self.top_bar.addStretch()
        settings_page = QWidget()
        layout = QVBoxLayout(settings_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(CARD_SPACING)
        layout.addLayout(self.top_bar)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.panel)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.videos)
        self.pages.addWidget(settings_page)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(WINDOW_MARGIN, WINDOW_MARGIN, WINDOW_MARGIN, WINDOW_MARGIN)
        central_layout.addWidget(self.pages)
        self.setCentralWidget(central)

        # Save the settings whenever any of them changes
        for section in (self.videos, *self.sections):
            for var in section.variables():
                var.changed.connect(self._save_settings)

        # Find the video card encoder right away if "Use GPU" was on last time, to show its QP field
        if self.encoding.use_gpu_var.get():
            self.encoding.check_gpu()

        # Undo and redo; after the check above, so its changes aren't a step
        untracked = {
            # The folder of the dialogs, the encoder the QP was set for, and the shown or hidden
            # settings in the custom motion aren't settings to undo
            self.videos.last_folder_var, self.encoding.gpu_qp_encoder_var,
            *(section.vars["expanded"] for section in self.motion.custom_sections),
        }
        for history, sections in zip(self.histories, ((self.videos,), self.sections)):
            for section in sections:
                for var in section.variables():
                    if var not in untracked:
                        history.track(var)
        for keys, command in ((UNDO_KEYS, self._undo), (REDO_KEYS, self._redo)):
            action = QAction(self)
            action.setShortcuts(keys)
            action.triggered.connect(command)
            self.addAction(action)
        # Text fields and number fields have their own undo of the text: let the keys reach
        # the shortcuts instead, so there is one undo for the whole page
        QApplication.instance().installEventFilter(self)

        self._fit_window()

    def _align_setting_labels(self):
        # Give the setting labels of all cards the same width, so their inputs line up
        labels = [label for label in self.settings_widget.findChildren(QLabel) if label.property("settingLabel")]
        width = max(label.sizeHint().width() for label in labels)
        for label in labels:
            label.setMinimumWidth(width)

    def _fit_window(self):
        # Open the window wide enough for the settings and tall enough for all of them,
        # unless the screen is too short for that
        for widget in self.findChildren(QWidget):
            widget.ensurePolished()
        margins = 2 * WINDOW_MARGIN + 2 * CARD_SPACING + self.top_bar.sizeHint().height()
        settings_size = self.settings_widget.sizeHint()
        panel_height = self.panel.sizeHint().height()
        scrollbar_width = self.scroll.verticalScrollBar().sizeHint().width()
        width = settings_size.width() + scrollbar_width + 2 * WINDOW_MARGIN
        max_height = self.screen().availableGeometry().height() * MAX_WINDOW_SCREEN_SHARE
        height = min(settings_size.height() + panel_height + margins, int(max_height))
        self.resize(width, height)
        # The window can be made shorter, down to a few rows of settings
        self.setMinimumSize(width, panel_height + margins + MIN_SETTINGS_HEIGHT)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            pressed = QKeySequence(event.keyCombination())
            if any(pressed.matches(keys) == QKeySequence.SequenceMatch.ExactMatch
                   for keys in UNDO_KEYS + REDO_KEYS):
                # Not taken by the field: the shortcut gets the key
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def _undo(self):
        # Nothing changes while rendering
        if not self.lock.locked:
            self.histories[self.pages.currentIndex()].undo()

    def _redo(self):
        if not self.lock.locked:
            self.histories[self.pages.currentIndex()].redo()

    def _show_settings(self):
        self.videos_count_label.setText(plural(len(self.videos.video_paths()), "video"))
        self.pages.setCurrentIndex(1)

    def _show_videos(self):
        self.pages.setCurrentIndex(0)

    def _save_settings(self, *args):
        settings = {}
        for section in (self.videos, *self.sections):
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
            QMessageBox.critical(self, "Error", str(e))
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
                "video_paths": self.videos.video_paths(), **paths, **look, **encoding,
                "motions": motions, "random_motion_order": random_motion_order
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

    def closeEvent(self, event):
        if self.control is None:
            QApplication.instance().removeEventFilter(self)
            self.videos.shutdown()
            event.accept()
            return

        # Stop rendering and close the window once the partial files are removed
        event.ignore()
        self.closing = True
        if not self.control.stopped:
            self._stop()

    def _close_if_requested(self):
        # Called when rendering ends; returns True if the window was closed
        if self.closing:
            self.control = None
            self.close()
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
        # Runs in the background thread; the results go to the main thread through the signals
        try:
            process_videos(
                on_progress=self.signals.progress.emit,
                on_video_progress=self.signals.video_progress.emit,
                control=control,
                **settings
            )
        except RenderCancelled:
            self.signals.cancelled.emit()
        except Exception as e:
            self.signals.error.emit(e)
        else:
            self.signals.done.emit()

    def _update_progress(self, processed, total, video_file):
        # Avoid division by zero when the folder has no videos
        self.panel.set_overall_progress(processed / max(total, 1))
        if video_file is not None:
            self.panel.reset_video_progress()
            self.processing_status = f"Processing video {processed + 1} of {total}: {video_file}"
            self.panel.set_status(self.processing_status)

    def _update_video_progress(self, stage, percent):
        self.panel.set_video_progress(stage, percent)

    def _on_done(self):
        if self._close_if_requested():
            return
        self.panel.set_status("Done")
        self._finish()
        QMessageBox.information(self, "Done", "All videos have been processed.")

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
        QMessageBox.critical(self, "Error", str(error))


def run():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Fusion looks the same on every system and follows its light/dark theme
    app.setStyle("Fusion")
    apply_style(app)
    window = UniversalWatermark()
    window.show()
    sys.exit(app.exec())
