import os
import queue
import signal
import subprocess
import threading

from functions.render_control import RenderCancelled


class FfmpegError(Exception):
    """Raised when ffmpeg exits with an error."""


def run_ffmpeg(binary, args, control=None, duration=None, on_progress=None):
    """
    Runs ffmpeg with args and returns its log (stderr).

    control: RenderControl; pausing suspends the ffmpeg process,
        stopping kills it and raises RenderCancelled.
    duration: length of the output in seconds, to report progress.
    on_progress: called with the progress in whole percent when it changes.
    """
    process = subprocess.Popen(
        [binary, "-hide_banner", "-nostats", "-progress", "pipe:1", *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        # Don't flash a console window on Windows when started from the GUI
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )

    # Read both pipes in the background, so ffmpeg never blocks on a full pipe
    # and this thread can react to pause/stop while ffmpeg is quiet
    progress_lines = queue.Queue()
    log_lines = []
    threading.Thread(target=read_lines, args=(process.stdout, progress_lines.put), daemon=True).start()
    log_reader = threading.Thread(target=read_lines, args=(process.stderr, log_lines.append), daemon=True)
    log_reader.start()

    suspended = False
    last_percent = None
    try:
        while process.poll() is None or not progress_lines.empty():
            if control is not None:
                if control.stopped:
                    raise RenderCancelled()
                if control.paused != suspended:
                    suspended = control.paused
                    set_suspended(process, suspended)

            try:
                line = progress_lines.get(timeout=0.1)
            except queue.Empty:
                continue

            # "-progress" prints "key=value" lines; out_time_us is the position in the output
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and duration and on_progress is not None:
                try:
                    seconds = int(value) / 1_000_000
                except ValueError:
                    continue
                percent = max(0, min(100, int(seconds * 100 / duration)))
                if percent != last_percent:
                    last_percent = percent
                    on_progress(percent)
    finally:
        if process.poll() is None:
            # A suspended process has to be resumed before it can exit
            if suspended:
                set_suspended(process, False)
            process.kill()
        process.wait()
        log_reader.join()

    log = "".join(log_lines)
    if process.returncode != 0:
        # The last lines of the log usually explain the error
        raise FfmpegError("ffmpeg failed:\n" + "\n".join(log.strip().splitlines()[-5:]))

    # The last reported position can be slightly short of the duration
    if duration and on_progress is not None and last_percent != 100:
        on_progress(100)
    return log


def read_lines(pipe, handle_line):
    for line in pipe:
        handle_line(line)


def set_suspended(process, suspended):
    # Pause or continue the whole ffmpeg process
    if os.name == "nt":
        import ctypes
        ntdll = ctypes.windll.ntdll
        (ntdll.NtSuspendProcess if suspended else ntdll.NtResumeProcess)(int(process._handle))
    else:
        os.kill(process.pid, signal.SIGSTOP if suspended else signal.SIGCONT)
