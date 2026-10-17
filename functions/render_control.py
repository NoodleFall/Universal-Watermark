import threading


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
    def paused(self):
        return not self._resumed.is_set()

    @property
    def stopped(self):
        return self._stopped

    def check(self):
        # Block while paused, then cancel if stop was requested
        self._resumed.wait()
        if self._stopped:
            raise RenderCancelled()
