import functools
import glob
import os
import shutil
import subprocess

from moviepy.config import FFMPEG_BINARY

from constants import RECOMMENDED_CRF

CPU_ENCODER = "libx264"

# H.264 encoders of video cards, in the order they are tried:
# NVIDIA (NVENC), Intel (Quick Sync), AMD on Windows (AMF), AMD/Intel on Linux (VAAPI)
GPU_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi")


@functools.cache
def find_gpu_encoder():
    """
    Returns (ffmpeg binary, encoder) for the first video card encoder that works,
    or None. ffmpeg bundled with moviepy usually lacks them, so a system ffmpeg
    is tried as well. The result is cached: the check takes a few seconds.
    """
    for binary in get_ffmpeg_binaries():
        for encoder in GPU_ENCODERS:
            if encoder_works(binary, encoder):
                return binary, encoder
    return None


def get_ffmpeg_binaries():
    binaries = [FFMPEG_BINARY]
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg and os.path.realpath(system_ffmpeg) != os.path.realpath(FFMPEG_BINARY):
        binaries.append(system_ffmpeg)
    return binaries


def encoder_works(binary, encoder):
    # Encode a few frames of a test picture with the same options a render would use
    if encoder == "h264_vaapi" and get_vaapi_device() is None:
        return False
    try:
        result = subprocess.run(
            [
                binary, "-hide_banner", "-loglevel", "error",
                *get_input_args(encoder),
                "-f", "lavfi", "-i", "testsrc2=size=256x256:rate=30:duration=0.2",
                "-vf", get_filter_tail(encoder),
                *get_encoder_args(encoder, RECOMMENDED_CRF, None),
                "-f", "null", "-",
            ],
            capture_output=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def get_vaapi_device():
    devices = sorted(glob.glob("/dev/dri/renderD*"))
    return devices[0] if devices else None


def get_input_args(encoder):
    # Options that must come before the inputs
    if encoder == "h264_vaapi":
        return ["-vaapi_device", get_vaapi_device()]
    return []


def get_filter_tail(encoder):
    # Pixel format conversion at the end of the filter chain for each encoder
    if encoder == CPU_ENCODER:
        return "format=yuv420p"
    if encoder == "h264_vaapi":
        # VAAPI encodes frames that are uploaded to the video card
        return "format=nv12,hwupload"
    return "format=nv12"


def get_encoder_args(encoder, crf, bitrate_kbps):
    """
    Video encoder options. crf: constant quality (lower is better);
    bitrate_kbps: target bitrate. Video cards have no CRF, so it maps to
    their constant quality mode with the same number, which gives similar,
    but not identical, quality.
    """
    args = ["-c:v", encoder]
    if encoder == CPU_ENCODER:
        args += ["-preset", "medium"]

    if crf is not None:
        quality = f"{crf:g}"
        qp = str(round(crf))
        args += {
            CPU_ENCODER: ["-crf", quality],
            "h264_nvenc": ["-rc", "vbr", "-cq", qp, "-b:v", "0"],
            "h264_qsv": ["-global_quality", qp],
            "h264_amf": ["-rc", "cqp", "-qp_i", qp, "-qp_p", qp, "-qp_b", qp],
            "h264_vaapi": ["-rc_mode", "CQP", "-qp", qp],
        }[encoder]
    elif bitrate_kbps is not None:
        bitrate = f"{max(round(bitrate_kbps), 1)}k"
        args += ["-b:v", bitrate]
        if encoder == "h264_vaapi":
            args += ["-rc_mode", "VBR"]
    return args
