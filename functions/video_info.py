import os
import subprocess

from moviepy.config import FFMPEG_BINARY
from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos

from functions.ffmpeg_runner import FfmpegError


def get_video_info(video_path):
    """
    Reads the video parameters without decoding it: duration, size,
    bitrates and audio info, as reported by ffmpeg.
    """
    infos = ffmpeg_parse_infos(video_path)
    width, height = infos["video_size"]
    # ffmpeg rotates phone videos while decoding, so the sides swap for 90/270 degrees
    if abs(infos.get("video_rotation", 0)) in (90, 270):
        width, height = height, width
    return {
        "duration": infos["duration"],
        "width": width,
        "height": height,
        "video_bitrate": infos.get("video_bitrate"),
        "total_bitrate": infos.get("bitrate"),
        "audio_found": infos.get("audio_found", False),
        "audio_bitrate": infos.get("audio_bitrate"),
        "audio_fps": infos.get("audio_fps"),
    }


def get_video_thumbnail(video_path, time, width, height):
    """
    One frame of the video at time (seconds), scaled down to fit width × height
    keeping its proportions, as PNG data; raises FfmpegError if ffmpeg can't read the video.
    """
    result = subprocess.run(
        [FFMPEG_BINARY, "-hide_banner", "-loglevel", "error", "-ss", str(time), "-i", video_path,
         "-frames:v", "1", "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease", "-f", "image2pipe", "-c:v", "png", "-"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        # Don't flash a console window on Windows when started from the GUI
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    )
    if result.returncode != 0 or not result.stdout:
        raise FfmpegError(result.stderr.decode("utf-8", "replace").strip() or "No frame found")
    return result.stdout
