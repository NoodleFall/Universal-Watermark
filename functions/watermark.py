import os
import random

from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip
from moviepy.Clip import Clip

from functions.audio import normalize_audio_file
from functions.bitrate import get_audio_bitrate, get_video_bitrate
from functions.render_control import RenderCancelled


def add_watermark(input_video_path, output_video_path, watermark_image_path, logger="bar",
                  width_percent=50, height_percent=None, opacity_percent=33, travel_time_seconds=30,
                  bitrate_kbps=None, target_lufs=-14.0):
    """
    width_percent: watermark width as a percentage of the video width.
    height_percent: watermark height as a percentage of the video height,
        or None to derive it from the width, keeping the image aspect ratio.
    opacity_percent: watermark opacity, from 0 (invisible) to 100 (opaque).
    travel_time_seconds: time for the watermark to travel from the top to the bottom.
    bitrate_kbps: video bitrate in kbit/s, or None to keep the bitrate of the original video.
    target_lufs: loudness to normalize the audio to, or None to keep the original audio.
    """
    # Load the video
    video = VideoFileClip(input_video_path)
    normalized_audio = None
    # Temporary WAV with the normalized audio, next to the output video.
    # The name prefix lets remove_partial_files() clean it up too
    normalized_audio_path = get_temp_file_path(output_video_path, "loudnorm.wav")
    cancelled = False

    try:
        # Bitrates to encode with: the custom video bitrate or the original one,
        # and always the original audio bitrate (None lets ffmpeg choose)
        audio_bitrate_kbps = get_audio_bitrate(video)
        if bitrate_kbps is None:
            bitrate_kbps = get_video_bitrate(video, audio_bitrate_kbps)
        print(f"Video bitrate: {f'{bitrate_kbps} kb/s' if bitrate_kbps else 'ffmpeg default'}, "
              f"audio bitrate: {f'{audio_bitrate_kbps} kb/s' if audio_bitrate_kbps else 'ffmpeg default'}")

        # Normalize the audio track, if requested
        if target_lufs is not None and video.audio is not None:
            if normalize_audio_file(input_video_path, normalized_audio_path, target_lufs, video.audio.fps):
                normalized_audio = AudioFileClip(normalized_audio_path)

        watermark = make_watermark_clip(
            video, watermark_image_path, width_percent, height_percent, opacity_percent, travel_time_seconds
        )

        # Overlay the watermark on the video
        final_video = CompositeVideoClip([video, watermark])

        # Use the normalized audio, if available
        if normalized_audio is not None:
            final_video = final_video.with_audio(normalized_audio)

        # Save the video with the watermark (and normalized audio, if requested)
        final_video.write_videofile(
            output_video_path,
            codec="libx264",
            audio_codec="aac",
            bitrate=f"{max(round(bitrate_kbps), 1)}k" if bitrate_kbps else None,
            audio_bitrate=f"{audio_bitrate_kbps}k" if audio_bitrate_kbps else None,
            # Create the temporary audio file next to the output video
            temp_audiofile_path=os.path.dirname(output_video_path),
            logger=logger
        )
    except RenderCancelled:
        cancelled = True
        raise
    finally:
        # Stop the ffmpeg processes that read the files; they must be closed
        # before the files can be removed on Windows
        video.close()
        if normalized_audio is not None:
            normalized_audio.close()
        if os.path.exists(normalized_audio_path):
            os.remove(normalized_audio_path)
        if cancelled:
            remove_partial_files(output_video_path)


def make_watermark_clip(video, watermark_image_path, width_percent, height_percent, opacity_percent,
                        travel_time_seconds):
    # Load the watermark image
    watermark = ImageClip(watermark_image_path)

    # Set the watermark duration to match the video duration
    watermark = watermark.with_duration(video.duration)

    # Set the watermark width as a percentage of the video width
    watermark_width = min(max(1, int(video.size[0] * width_percent / 100)), video.size[0])
    if height_percent is None:
        # Keep the image aspect ratio
        watermark_height = int(watermark.size[1] * (watermark_width / watermark.size[0]))
    else:
        watermark_height = int(video.size[1] * height_percent / 100)
    # Don't let the watermark be empty or larger than the video
    watermark_height = min(max(1, watermark_height), video.size[1])
    # Pass both sides explicitly: with width= and height= moviepy ignores the width
    watermark = watermark.resized(new_size=(watermark_width, watermark_height))

    # Set the watermark opacity
    watermark = watermark.with_opacity(min(max(opacity_percent, 0), 100) / 100)

    # Time it takes for the watermark to travel from top to bottom
    animation_duration = travel_time_seconds  # in seconds

    # Function to animate the watermark position
    def animate_position(t):
        # Compute the Y position based on time
        y_position = (t % animation_duration) / animation_duration * (video.size[1] - watermark.size[1])

        # Change the horizontal position randomly every 5 seconds
        x_position = random.randint(0, video.size[0] - watermark.size[0]) if t % 5 == 0 else None

        # If x_position hasn't changed, use the last value
        if not hasattr(animate_position, 'last_x_position'):
            animate_position.last_x_position = 0  # default starting position
        if x_position is not None:
            animate_position.last_x_position = x_position

        return (animate_position.last_x_position, y_position)

    # Apply the animation to the watermark
    return watermark.with_position(animate_position)


def get_temp_file_path(output_video_path, suffix):
    # "<output name>TEMP_MPY_<suffix>" next to the output video, like moviepy's own temporary files
    name = os.path.splitext(os.path.basename(output_video_path))[0]
    return os.path.join(os.path.dirname(output_video_path), name + Clip._TEMP_FILES_PREFIX + suffix)


def remove_partial_files(output_video_path):
    # Remove the unfinished output video
    if os.path.exists(output_video_path):
        os.remove(output_video_path)

    # Remove the temporary files, named "<video name>TEMP_MPY_..."
    output_dir = os.path.dirname(output_video_path) or "."
    name = os.path.splitext(os.path.basename(output_video_path))[0]
    for file_name in os.listdir(output_dir):
        if file_name.startswith(name + Clip._TEMP_FILES_PREFIX):
            os.remove(os.path.join(output_dir, file_name))
