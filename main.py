import os

from constants import CODEC_CONTAINERS, CODEC_H264, OUTPUT_EXTENSION_OVERRIDES, VIDEO_EXTENSIONS
from functions.watermark import add_watermark


def get_output_extension(original_extension, codec):
    # Keep the original extension unless the container can't hold the codec with AAC audio
    if codec == CODEC_H264:
        return OUTPUT_EXTENSION_OVERRIDES.get(original_extension.lower(), original_extension)
    return original_extension if original_extension.lower() in CODEC_CONTAINERS[codec] else ".mp4"


def get_output_video_path(output_folder_path, video_file, video_files, codec=CODEC_H264):
    name, original_extension = os.path.splitext(video_file)
    extension = get_output_extension(original_extension, codec)
    # Don't overwrite the result of another video with the same name, e.g. clip.webm and clip.mp4
    if extension != original_extension and any(f.lower() == (name + extension).lower() for f in video_files):
        name += "_" + original_extension[1:]
    return os.path.join(output_folder_path, f"watermarked_{name}{extension}")


def main(raw_videos_path, output_folder_path, watermark_image_path, on_progress=None, on_video_progress=None, control=None,
         width_percent=50, height_percent=None, opacity_percent=33, travel_time_seconds=30, bitrate_kbps=None,
         target_lufs=-14.0, crf=None, use_gpu=False, codec=CODEC_H264):
    # Create the output folder for watermarked videos if it doesn't exist
    if not os.path.exists(output_folder_path):
        os.makedirs(output_folder_path)

    # Get a list of all video files in the folder
    video_files = [f for f in os.listdir(raw_videos_path) if f.lower().endswith(VIDEO_EXTENSIONS)]

    # Process each video
    for i, video_file in enumerate(video_files):
        # Wait here if paused and stop if requested before starting the next video
        if control is not None:
            control.check()

        # Report progress to the caller (e.g. the GUI)
        if on_progress is not None:
            on_progress(i, len(video_files), video_file)

        input_video_path = os.path.join(raw_videos_path, video_file)
        output_video_path = get_output_video_path(output_folder_path, video_file, video_files, codec)

        print(f"Processing video: {video_file}")
        add_watermark(
            input_video_path,
            output_video_path,
            watermark_image_path,
            width_percent=width_percent,
            height_percent=height_percent,
            opacity_percent=opacity_percent,
            travel_time_seconds=travel_time_seconds,
            bitrate_kbps=bitrate_kbps,
            target_lufs=target_lufs,
            crf=crf,
            use_gpu=use_gpu,
            codec=codec,
            control=control,
            on_progress=on_video_progress
        )
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

    # Run batch processing, showing the progress of each video in the same console line
    main(raw_videos_path, output_folder_path, watermark_image_path,
         on_video_progress=lambda percent: print(f"\rRendering: {percent}%", end="\n" if percent == 100 else "", flush=True))
