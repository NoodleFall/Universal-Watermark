import os
import random
import threading

import numpy as np
from moviepy import CompositeVideoClip, ImageClip, VideoFileClip
from moviepy.Clip import Clip
from moviepy.audio.AudioClip import AudioClip
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


def normalize_audio_clip(audio_clip, target_lufs=-14.0, fps=44100):
    """
    Approximate normalization to a target loudness level in LUFS.
    Done via RMS (dBFS ≈ LUFS in most cases).

    target_lufs: target level, e.g. -14.0 (for streaming platforms).
    """
    if audio_clip is None:
        return None

    try:
        snd = audio_clip.to_soundarray(fps=fps)  # [samples, channels] or [samples]
    except Exception as e:
        print(f"Failed to read audio for normalization: {e}")
        return audio_clip

    if snd.size == 0:
        return audio_clip

    # Downmix to mono for loudness calculation
    if snd.ndim == 2:
        snd_mono = snd.mean(axis=1)
    else:
        snd_mono = snd

    # RMS
    rms = float(np.sqrt(np.mean(snd_mono ** 2)))
    if rms == 0:
        print("[Normalization] Complete silence, skipping")
        return audio_clip

    # dBFS ≈ LUFS
    current_lufs = 20 * np.log10(rms + 1e-12)

    gain_db = target_lufs - current_lufs
    # Convert dB → factor
    factor = 10 ** (gain_db / 20.0)

    # Limit boost/cut to reasonable bounds to avoid extreme results
    factor = float(np.clip(factor, 0.1, 10.0))

    print(f"[LUFS normalization] current ≈ {current_lufs:.2f} LUFS, target = {target_lufs:.2f} LUFS, gain = {gain_db:.2f} dB, factor = {factor:.3f}")

    snd_norm = snd * factor
    # Guard against amplitude clipping
    snd_norm = np.clip(snd_norm, -1.0, 1.0)

    def make_frame(t):
        t_arr = np.array(t, dtype=float)
        idx = (t_arr * fps).astype(int)
        idx = np.clip(idx, 0, snd_norm.shape[0] - 1)
        return snd_norm[idx]

    normalized_audio = AudioClip(make_frame, duration=audio_clip.duration, fps=fps)
    return normalized_audio



def add_watermark(input_video_path, output_video_path, watermark_image_path, logger="bar"):
    # Load the video
    video = VideoFileClip(input_video_path)

    # Normalize the audio track
    normalized_audio = normalize_audio_clip(video.audio, target_lufs=-14.0)

    # Load the watermark image
    watermark = ImageClip(watermark_image_path)

    # Set the watermark duration to match the video duration
    watermark = watermark.with_duration(video.duration)

    # Set the watermark size: 50% of the video width
    watermark_width = int(video.size[0] * 0.50)
    watermark_height = int(watermark.size[1] * (watermark_width / watermark.size[0]))
    watermark = watermark.resized(width=watermark_width, height=watermark_height)

    # Set the watermark opacity (33%)
    watermark = watermark.with_opacity(0.33)

    # Time it takes for the watermark to travel from top to bottom
    animation_duration = 30  # in seconds

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
    watermark = watermark.with_position(animate_position)

    # Overlay the watermark on the video
    final_video = CompositeVideoClip([video, watermark])

    # Use the normalized audio, if available
    if normalized_audio is not None:
        final_video = final_video.with_audio(normalized_audio)

    # Save the video with the watermark and normalized audio
    try:
        final_video.write_videofile(
            output_video_path,
            codec="libx264",
            audio_codec="aac",
            # Create the temporary audio file next to the output video
            temp_audiofile_path=os.path.dirname(output_video_path),
            logger=logger
        )
    except RenderCancelled:
        remove_partial_files(output_video_path)
        raise
    finally:
        # Stop the ffmpeg process that reads the source video
        video.close()


def remove_partial_files(output_video_path):
    # Remove the unfinished output video
    if os.path.exists(output_video_path):
        os.remove(output_video_path)

    # Remove moviepy's temporary audio file, named "<video name>TEMP_MPY_..."
    output_dir = os.path.dirname(output_video_path) or "."
    name = os.path.splitext(os.path.basename(output_video_path))[0]
    for file_name in os.listdir(output_dir):
        if file_name.startswith(name + Clip._TEMP_FILES_PREFIX):
            os.remove(os.path.join(output_dir, file_name))


def main(raw_videos_path, output_folder_path, watermark_image_path, on_progress=None, on_video_progress=None, control=None):
    # Create the output folder for watermarked videos if it doesn't exist
    if not os.path.exists(output_folder_path):
        os.makedirs(output_folder_path)

    # Get a list of all video files in the folder
    video_files = [f for f in os.listdir(raw_videos_path) if f.endswith(('.mp4', '.avi', '.mov', '.mkv', '.MP4'))]

    # Process each video
    for i, video_file in enumerate(video_files):
        # Wait here if paused and stop if requested before starting the next video
        if control is not None:
            control.check()

        # Report progress to the caller (e.g. the GUI)
        if on_progress is not None:
            on_progress(i, len(video_files), video_file)

        input_video_path = os.path.join(raw_videos_path, video_file)
        output_video_path = os.path.join(output_folder_path, f"watermarked_{video_file}")

        # Use a logger that reports per-video progress and handles pause/stop, if requested
        if on_video_progress is not None or control is not None:
            logger = VideoProgressLogger(on_video_progress, control)
        else:
            logger = "bar"

        print(f"Processing video: {video_file}")
        add_watermark(input_video_path, output_video_path, watermark_image_path, logger=logger)
        print(f"Video saved: {output_video_path}")

    # Report that all videos have been processed
    if on_progress is not None:
        on_progress(len(video_files), len(video_files), None)


if __name__ == "__main__":
    # Path to the folder with raw videos
    raw_videos_path = "raw_videos"

    # Path to the folder for saving watermarked videos
    output_folder_path = "watermarked_videos"

    # Path to the watermark image
    watermark_image_path = "watermark.png"

    # Run batch processing
    main(raw_videos_path, output_folder_path, watermark_image_path)
