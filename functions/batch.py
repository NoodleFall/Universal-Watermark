import os
import random

from constants import (
    CODEC_CONTAINERS,
    CODEC_H264,
    MOTION_TOP_TO_BOTTOM,
    OUTPUT_EXTENSION_OVERRIDES,
)
from functions.console_progress import end_progress_line, print_progress
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


def get_output_video_paths(output_folder_path, video_paths, codec=CODEC_H264):
    # Paths of the results of the videos, in the same order. Videos with the same name from
    # different folders get "_2", "_3"… so they don't overwrite each other's result
    video_files = [os.path.basename(path) for path in video_paths]
    output_paths = []
    taken = set()
    for video_file in video_files:
        output_path = get_output_video_path(output_folder_path, video_file, video_files, codec)
        base, extension = os.path.splitext(output_path)
        number = 2
        while output_path.lower() in taken:
            output_path = f"{base}_{number}{extension}"
            number += 1
        taken.add(output_path.lower())
        output_paths.append(output_path)
    return output_paths


def process_videos(video_paths, output_folder_path, watermark_image_path, on_progress=None, on_video_progress=None, control=None,
         width_percent=50, height_percent=None, opacity_percent=33, bitrate_kbps=None,
         motions=None, random_motion_order=False,
         target_lufs=-14.0, crf=None, use_gpu=False, codec=CODEC_H264, qp=None):
    # motions: watermark motions to use, each a dict of the motion settings of add_watermark(),
    # e.g. {"motion": MOTION_BOUNCE, "bounce_speed_percent": 10}; the videos take them in turn,
    # or each video takes a random one with random_motion_order. By default, all videos move top to bottom
    if not motions:
        motions = [{"motion": MOTION_TOP_TO_BOTTOM}]

    # Create the output folder for watermarked videos if it doesn't exist
    if not os.path.exists(output_folder_path):
        os.makedirs(output_folder_path)

    # In the order given: the motions go in turn in it
    output_video_paths = get_output_video_paths(output_folder_path, video_paths, codec)

    def report_video_progress(stage, percent):
        # Show the progress of the current stage in the console and report it to the caller (e.g. the GUI)
        print_progress(stage, percent)
        if on_video_progress is not None:
            on_video_progress(stage, percent)

    # Process each video
    for i, (input_video_path, output_video_path) in enumerate(zip(video_paths, output_video_paths)):
        video_file = os.path.basename(input_video_path)
        # Wait here if paused and stop if requested before starting the next video
        if control is not None:
            control.check()

        # Report progress to the caller (e.g. the GUI)
        if on_progress is not None:
            on_progress(i, len(video_paths), video_file)

        print(f"Processing video: {video_file}")
        motion_settings = random.choice(motions) if random_motion_order else motions[i % len(motions)]
        if len(motions) > 1:
            print(f"Watermark motion: {motion_settings['motion']}")
        try:
            add_watermark(
                input_video_path,
                output_video_path,
                watermark_image_path,
                width_percent=width_percent,
                height_percent=height_percent,
                opacity_percent=opacity_percent,
                **motion_settings,
                bitrate_kbps=bitrate_kbps,
                target_lufs=target_lufs,
                crf=crf,
                use_gpu=use_gpu,
                codec=codec,
                qp=qp,
                control=control,
                on_progress=report_video_progress
            )
        except BaseException:
            # Don't let the next message continue the unfinished progress line
            end_progress_line()
            raise
        print(f"Video saved: {output_video_path}")

    # Report that all videos have been processed
    if on_progress is not None:
        on_progress(len(video_paths), len(video_paths), None)

