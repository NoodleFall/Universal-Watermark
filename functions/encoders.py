import functools
import glob
import os
import shutil
import subprocess

from moviepy.config import FFMPEG_BINARY

from constants import CODEC_AV1, CODEC_H264, CODEC_HEVC, RECOMMENDED_CRF

# Encoders of each codec. CPU encoders and video card encoders are tried in this order:
# video cards: NVIDIA (NVENC), Intel (Quick Sync), AMD on Windows (AMF), AMD/Intel on Linux (VAAPI)
CPU_ENCODERS = {
    CODEC_H264: ("libx264",),
    CODEC_HEVC: ("libx265",),
    # SVT-AV1 is many times faster than libaom, but isn't in every ffmpeg build
    CODEC_AV1: ("libsvtav1", "libaom-av1"),
}
GPU_ENCODERS = {
    CODEC_H264: ("h264_nvenc", "h264_qsv", "h264_amf", "h264_vaapi"),
    CODEC_HEVC: ("hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_vaapi"),
    CODEC_AV1: ("av1_nvenc", "av1_qsv", "av1_amf", "av1_vaapi"),
}
ALL_CPU_ENCODERS = {encoder for encoders in CPU_ENCODERS.values() for encoder in encoders}


@functools.cache
def find_cpu_encoder(codec):
    """
    Returns (ffmpeg binary, encoder) for the first CPU encoder of the codec that works,
    or None. The result is cached: the check can take a few seconds.
    """
    print(f"Checking CPU encoders for {codec}...")
    return find_working_encoder(CPU_ENCODERS[codec])


@functools.cache
def find_gpu_encoder(codec):
    """
    Returns (ffmpeg binary, encoder) for the first video card encoder of the codec
    that works, or None. The result is cached: the check takes a few seconds.
    """
    print(f"Checking video card encoders for {codec}...")
    return find_working_encoder(GPU_ENCODERS[codec])


def find_working_encoder(encoders):
    # ffmpeg bundled with moviepy lacks video card encoders and SVT-AV1,
    # so a system ffmpeg is tried as well
    for binary in get_ffmpeg_binaries():
        for encoder in encoders:
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
    if encoder.endswith("_vaapi") and get_vaapi_device() is None:
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
            timeout=60,
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
    if encoder.endswith("_vaapi"):
        return ["-vaapi_device", get_vaapi_device()]
    return []


def get_filter_tail(encoder):
    # Pixel format conversion at the end of the filter chain for each encoder
    if encoder in ALL_CPU_ENCODERS:
        return "format=yuv420p"
    if encoder.endswith("_vaapi"):
        # VAAPI encodes frames that are uploaded to the video card
        return "format=nv12,hwupload"
    return "format=nv12"


def get_encoder_args(encoder, crf, bitrate_kbps, qp=None):
    """
    Video encoder options. crf: constant quality on the H.264 (x264) scale, lower is
    better; bitrate_kbps: target bitrate. Other encoders use their own quality scales,
    so the CRF is converted to give a similar quality, not an identical one.
    qp: constant quality of a video card encoder on its own scale (see get_gpu_qp_scale);
    when set, it's used for video cards as is, instead of the converted crf.
    """
    args = ["-c:v", encoder]
    args += {
        "libx264": ["-preset", "medium"],
        "libx265": ["-preset", "medium", "-x265-params", "log-level=error"],
        # Speed settings that keep AV1 encoding on the CPU bearable
        "libsvtav1": ["-preset", "8", "-svtav1-params", "verbosity=0"],
        "libaom-av1": ["-cpu-used", "8", "-row-mt", "1"],
    }.get(encoder, [])

    if qp is not None and encoder not in ALL_CPU_ENCODERS:
        args += get_gpu_quality_args(encoder, qp)
    elif crf is not None:
        args += get_quality_args(encoder, crf)
    elif bitrate_kbps is not None:
        args += ["-b:v", f"{max(round(bitrate_kbps), 1)}k"]
        if encoder.endswith("_vaapi"):
            args += ["-rc_mode", "VBR"]
    return args


def get_quality_args(encoder, crf):
    # Constant quality options for each encoder, from a CRF on the x264 scale (0-51)
    if encoder == "libx264":
        return ["-crf", f"{crf:g}"]
    if encoder == "libx265":
        return ["-crf", f"{get_hevc_crf(crf):g}"]
    if encoder in ("libsvtav1", "libaom-av1"):
        av1_crf = str(get_av1_crf(crf))
        return ["-crf", av1_crf] + (["-b:v", "0"] if encoder == "libaom-av1" else [])

    # Video cards have no CRF: use their constant quality mode instead
    return get_gpu_quality_args(encoder, convert_crf_to_gpu_qp(encoder, crf))


def get_gpu_qp_scale(encoder):
    # (recommended QP, highest QP) of a video card encoder; the recommended one
    # gives about the quality of the recommended x264 CRF
    return convert_crf_to_gpu_qp(encoder, RECOMMENDED_CRF), 255 if uses_av1_quality_index(encoder) else 51


def convert_crf_to_gpu_qp(encoder, crf):
    # QP on the scale of a video card encoder for an x264 CRF
    if uses_av1_quality_index(encoder):
        return round(get_av1_crf(crf) * 255 / 63)
    if encoder.startswith("hevc_"):
        # HEVC uses the same scale on video cards and in x265
        return round(get_hevc_crf(crf))
    return round(crf)


def uses_av1_quality_index(encoder):
    # AV1 quality index of AMF, Quick Sync and VAAPI goes from 0 to 255
    return encoder.startswith("av1_") and not encoder.endswith("_nvenc")


def get_gpu_quality_args(encoder, qp):
    # Constant quality options of a video card encoder for a QP on its own scale
    qp = str(round(qp))
    if encoder.endswith("_nvenc"):
        return ["-rc", "vbr", "-cq", qp, "-b:v", "0"]
    if encoder.endswith("_qsv"):
        return ["-global_quality", qp]
    if encoder.endswith("_amf"):
        return ["-rc", "cqp", "-qp_i", qp, "-qp_p", qp, *(["-qp_b", qp] if encoder.startswith("h264") else [])]
    return ["-rc_mode", "CQP", "-qp", qp]


def get_hevc_crf(crf):
    # HEVC CRF that looks about like an x264 CRF: measured on phone videos,
    # x265's 28 matches x264's 23 by SSIM
    return min(crf + 5, 51)


def get_av1_crf(crf):
    # AV1 CRF (0-63) that looks about like an x264 CRF: measured on phone videos,
    # x264's 23 matches AV1's 42 by SSIM
    return max(1, min(63, round(crf * 42 / 23)))
