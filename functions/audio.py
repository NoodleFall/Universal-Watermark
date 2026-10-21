import json
import math
import re

from moviepy.config import FFMPEG_BINARY

from constants import LOUDNESS_RANGE_LU, LOUDNESS_TRUE_PEAK_DB
from functions.console_progress import end_progress_line, print_progress
from functions.ffmpeg_runner import FfmpegError, run_ffmpeg


def normalize_audio_file(input_video_path, output_audio_path, target_lufs, sample_rate, control=None, duration=None):
    """
    Normalizes the audio of a video to target_lufs with ffmpeg's loudnorm filter
    (EBU R128): the first pass measures the loudness, the second one applies it.
    Peaks are limited to LOUDNESS_TRUE_PEAK_DB instead of being cut off.

    Writes the result to output_audio_path (WAV) and returns True,
    or returns False if the audio couldn't be normalized.
    control: RenderControl to pause or stop the normalization.
    duration: length of the video in seconds, to show the progress of both passes in the console.
    """
    loudnorm = f"loudnorm=I={target_lufs}:TP={LOUDNESS_TRUE_PEAK_DB}:LRA={LOUDNESS_RANGE_LU}"

    # First pass: measure the loudness
    try:
        measured = measure_loudness(input_video_path, loudnorm, control, duration)
    except (OSError, FfmpegError, ValueError) as e:
        end_progress_line()
        print(f"Failed to measure the loudness for normalization: {e}")
        return False

    # Complete silence can't be normalized
    if not math.isfinite(float(measured["input_i"])):
        print("[Normalization] Complete silence, skipping")
        return False

    print(f"[LUFS normalization] current = {float(measured['input_i']):.2f} LUFS, "
          f"target = {target_lufs:.2f} LUFS, true peak = {float(measured['input_tp']):.2f} dBTP")

    # Second pass: normalize using the measured values
    second_pass = (
        f"{loudnorm}"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        f":linear=true"
    )
    try:
        run_ffmpeg(FFMPEG_BINARY, [
            "-y", "-i", input_video_path, "-vn",
            "-af", second_pass,
            # loudnorm works at 192 kHz internally, so return to the original rate
            "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            output_audio_path,
        ], control, duration, lambda percent: print_progress("Normalizing audio", percent))
    except (OSError, FfmpegError) as e:
        end_progress_line()
        print(f"Failed to normalize the audio: {e}")
        return False
    return True


def measure_loudness(input_video_path, loudnorm, control=None, duration=None):
    # Returns the loudnorm measurements of the first pass as a dict of strings
    log = run_ffmpeg(FFMPEG_BINARY, ["-i", input_video_path, "-vn", "-af", f"{loudnorm}:print_format=json", "-f", "null", "-"],
                     control, duration, lambda percent: print_progress("Measuring loudness", percent))
    # loudnorm prints its JSON at the end of ffmpeg's log
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", log)
    if not match:
        raise ValueError("loudnorm didn't report the measured loudness")
    return json.loads(match.group(0))
