import threading

from proglog import TqdmProgressBarLogger


class RenderCancelled(Exception):
    """Raised when the user stops rendering."""


class RenderControl:
    """
    Lets another thread (e.g. the GUI) pause, resume and stop rendering.
    """

    def __init__(self):
        self._resumed = threading.Event()
        self._resumed.set()
        self._stopped = False

    def pause(self):
        self._resumed.clear()

    def resume(self):
        self._resumed.set()

    def stop(self):
        self._stopped = True
        # Wake up the render thread if it is paused
        self._resumed.set()

    @property
    def stopped(self):
        return self._stopped

    def wait_if_paused(self):
        self._resumed.wait()

    def check(self):
        # Block while paused, then cancel if stop was requested
        self.wait_if_paused()
        if self._stopped:
            raise RenderCancelled()


class VideoProgressLogger(TqdmProgressBarLogger):
    """
    Keeps moviepy's console progress bars, reports frame rendering
    progress of the current video via a callback and handles pause/stop.
    """

    def __init__(self, on_video_progress=None, control=None):
        super().__init__()
        self.on_video_progress = on_video_progress
        self.control = control
        self.last_percent = None

    def bars_callback(self, bar, attr, value, old_value=None):
        super().bars_callback(bar, attr, value, old_value)

        # "frame_index" is the bar moviepy uses while writing video frames
        if bar != "frame_index" or attr != "index":
            # Audio is being written: allow pausing, but don't cancel here,
            # because moviepy doesn't close its audio writer on errors
            if self.control is not None:
                self.control.wait_if_paused()
            return

        if self.control is not None:
            self.control.check()

        total = self.bars[bar]["total"]
        if not total or self.on_video_progress is None:
            return

        # Report only when the whole percent changes to avoid flooding the caller
        percent = min(100, int((value + 1) * 100 / total))
        if percent != self.last_percent:
            self.last_percent = percent
            self.on_video_progress(percent)
