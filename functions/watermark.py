import os
import random

from PIL import Image

from constants import CODEC_H264, CODEC_HEVC, DEFAULT_POSITION_CHANGE_SECONDS, TEMP_FILE_MARKER
from functions.audio import normalize_audio_file
from functions.bitrate import get_audio_bitrate, get_video_bitrate
from functions.encoders import find_cpu_encoder, find_gpu_encoder, get_encoder_args, get_filter_tail, get_input_args
from functions.ffmpeg_runner import FfmpegError, run_ffmpeg
from functions.video_info import get_video_info


def add_watermark(input_video_path, output_video_path, watermark_image_path,
                  width_percent=50, height_percent=None, opacity_percent=33, travel_time_seconds=30,
                  position_change_seconds=DEFAULT_POSITION_CHANGE_SECONDS,
                  bitrate_kbps=None, target_lufs=-14.0, crf=None, use_gpu=False, codec=CODEC_H264, qp=None,
                  control=None, on_progress=None):
    """
    Renders the video with a moving watermark in one ffmpeg run.

    width_percent: watermark width as a percentage of the video width.
    height_percent: watermark height as a percentage of the video height,
        or None to derive it from the width, keeping the image aspect ratio.
    opacity_percent: watermark opacity, from 0 (invisible) to 100 (opaque).
    travel_time_seconds: time for the watermark to travel from the top to the bottom.
    position_change_seconds: how often the watermark jumps to a new random horizontal position.
    bitrate_kbps: video bitrate in kbit/s, or None to keep the bitrate of the original video.
    target_lufs: loudness to normalize the audio to, or None to keep the original audio.
    crf: constant quality (lower is better, x264 range 0-51); when set,
        the encoder picks the bitrate itself and bitrate_kbps is ignored.
    use_gpu: encode with the video card, if one is found; otherwise the CPU is used.
    codec: one of VIDEO_CODECS.
    qp: constant quality of the video card encoder on its own scale; when set, it's used
        instead of crf for the video card (crf is still used if the CPU takes over).
    control: RenderControl to pause or stop rendering.
    on_progress: called with the rendering progress of this video in whole percent.
    """
    info = get_video_info(input_video_path)

    # Bitrates to encode with: the custom video bitrate or the original one
    # (unless a CRF is used), and the original audio bitrate (None lets ffmpeg choose)
    audio_bitrate_kbps = get_audio_bitrate(info)
    if crf is None and bitrate_kbps is None:
        bitrate_kbps = get_video_bitrate(info)

    # Encoders to try: the video card, if requested and available, then the CPU.
    # Video cards have limits (e.g. the largest frame size), so a video they
    # can't encode is rendered on the CPU instead
    cpu_encoder = find_cpu_encoder(codec)
    if cpu_encoder is None:
        raise FfmpegError(f"No working {codec} encoder was found in ffmpeg")
    encoders = [cpu_encoder]
    if use_gpu:
        gpu_encoder = find_gpu_encoder(codec)
        if gpu_encoder is not None:
            encoders.insert(0, gpu_encoder)
        else:
            print(f"No video card encoder for {codec} found, using the CPU")

    # Temporary WAV with the normalized audio, next to the output video.
    # The name marker lets remove_partial_files() clean it up too
    normalized_audio_path = get_temp_file_path(output_video_path, "loudnorm.wav")
    succeeded = False
    try:
        # Normalize the audio track, if requested
        use_normalized_audio = False
        if target_lufs is not None and info["audio_found"]:
            use_normalized_audio = normalize_audio_file(
                input_video_path, normalized_audio_path, target_lufs, info["audio_fps"], control
            )

        watermark_filter = get_watermark_filter(
            info, watermark_image_path, width_percent, height_percent, opacity_percent, travel_time_seconds,
            position_change_seconds
        )
        for binary, encoder in encoders:
            if qp is not None and (binary, encoder) != cpu_encoder:
                video_quality = f"QP {qp:g}"
            elif crf is not None:
                video_quality = f"CRF {crf:g} (H.264 scale)"
            else:
                video_quality = f"bitrate {f'{bitrate_kbps} kb/s' if bitrate_kbps else 'encoder default'}"
            print(f"Encoder: {encoder}, video {video_quality}, "
                  f"audio bitrate: {f'{audio_bitrate_kbps} kb/s' if audio_bitrate_kbps else 'ffmpeg default'}")
            args = [
                *get_input_args(encoder),
                "-y",
                "-i", input_video_path,
                # The watermark image repeats for as long as the video lasts
                "-loop", "1", "-i", watermark_image_path,
                *(["-i", normalized_audio_path] if use_normalized_audio else []),
                "-filter_complex", f"{watermark_filter},{get_filter_tail(encoder)}[video]",
                "-map", "[video]",
                *get_audio_args(info, use_normalized_audio, audio_bitrate_kbps),
                *get_encoder_args(encoder, crf, bitrate_kbps, qp),
                *get_codec_tag_args(codec, output_video_path),
                output_video_path,
            ]
            try:
                run_ffmpeg(binary, args, control, info["duration"], on_progress)
                break
            except FfmpegError as e:
                if (binary, encoder) == cpu_encoder:
                    raise
                print(f"The video card couldn't encode this video, rendering it on the CPU instead:\n{e}")
                if os.path.exists(output_video_path):
                    os.remove(output_video_path)
                if on_progress is not None:
                    on_progress(0)
        succeeded = True
    finally:
        if os.path.exists(normalized_audio_path):
            os.remove(normalized_audio_path)
        # Don't leave an unfinished video when rendering is stopped or fails
        if not succeeded:
            remove_partial_files(output_video_path)


def get_watermark_filter(info, watermark_image_path, width_percent, height_percent, opacity_percent,
                         travel_time_seconds, position_change_seconds):
    # ffmpeg filter that scales the watermark, sets its opacity and moves it over the video
    watermark_width, watermark_height = get_watermark_size(info, watermark_image_path, width_percent, height_percent)
    opacity = min(max(opacity_percent, 0), 100) / 100

    # Top to bottom once every travel_time_seconds
    y = f"mod(t,{travel_time_seconds:g})/{travel_time_seconds:g}*(H-h)"
    # A new random horizontal position every position_change_seconds: a pseudo-random
    # number from the number of the time slot, with a random seed for each video
    seed = random.uniform(0, 1000)
    x = f"(W-w)*mod(abs(sin(floor(t/{position_change_seconds:g})*12.9898+{seed:.4f}))*43758.5453,1)"

    return (
        f"[1:v]scale={watermark_width}:{watermark_height},format=rgba,colorchannelmixer=aa={opacity:g}[watermark];"
        f"[0:v][watermark]overlay=x='{x}':y='{y}':shortest=1"
    )


def get_watermark_size(info, watermark_image_path, width_percent, height_percent):
    with Image.open(watermark_image_path) as image:
        image_width, image_height = image.size

    # Watermark width as a percentage of the video width
    watermark_width = min(max(1, int(info["width"] * width_percent / 100)), info["width"])
    if height_percent is None:
        # Keep the image aspect ratio
        watermark_height = int(image_height * (watermark_width / image_width))
    else:
        watermark_height = int(info["height"] * height_percent / 100)
    # Don't let the watermark be empty or larger than the video
    watermark_height = min(max(1, watermark_height), info["height"])
    return watermark_width, watermark_height


def get_codec_tag_args(codec, output_video_path):
    # Apple devices only play HEVC in MP4/MOV when it's tagged "hvc1" instead of ffmpeg's "hev1"
    if codec == CODEC_HEVC and output_video_path.lower().endswith((".mp4", ".mov", ".m4v")):
        return ["-tag:v", "hvc1"]
    return []


def get_audio_args(info, use_normalized_audio, audio_bitrate_kbps):
    if use_normalized_audio:
        # The normalized WAV is the third input
        audio_map = ["-map", "2:a:0"]
    elif info["audio_found"]:
        audio_map = ["-map", "0:a:0"]
    else:
        return []
    return [*audio_map, "-c:a", "aac", *(["-b:a", f"{audio_bitrate_kbps}k"] if audio_bitrate_kbps else [])]


def get_temp_file_path(output_video_path, suffix):
    # "<output name><TEMP_FILE_MARKER><suffix>" next to the output video
    name = os.path.splitext(os.path.basename(output_video_path))[0]
    return os.path.join(os.path.dirname(output_video_path), name + TEMP_FILE_MARKER + suffix)


def remove_partial_files(output_video_path):
    # Remove the unfinished output video
    if os.path.exists(output_video_path):
        os.remove(output_video_path)

    # Remove the temporary files, named "<video name><TEMP_FILE_MARKER>..."
    output_dir = os.path.dirname(output_video_path) or "."
    name = os.path.splitext(os.path.basename(output_video_path))[0]
    for file_name in os.listdir(output_dir):
        if file_name.startswith(name + TEMP_FILE_MARKER):
            os.remove(os.path.join(output_dir, file_name))
