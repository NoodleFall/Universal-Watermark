import argparse
import os
import sys

from constants import (
    CODEC_AV1,
    CODEC_H264,
    CODEC_HEVC,
    DEFAULT_BOUNCE_SPEED_PERCENT,
    DEFAULT_POSITION_CHANGE_SECONDS,
    DEFAULT_TRAVEL_TIME_SECONDS,
    LOUDNESS_PRESETS,
    MAX_BITRATE_KBPS,
    MAX_BOUNCE_SPEED_PERCENT,
    MAX_CRF,
    MAX_GPU_QP,
    MAX_PERCENT,
    MAX_POSITION_CHANGE_SECONDS,
    MAX_TRAVEL_TIME_SECONDS,
    MOTION_BOUNCE,
    MOTION_TOP_TO_BOTTOM,
    RECOMMENDED_CRF,
)
from functions.batch import process_videos
from functions.video_files import find_videos, is_video_file, sort_videos
from ui.number_input import InvalidInput, parse_field

# Names of the motions and codecs on the command line
MOTIONS = {"top-to-bottom": MOTION_TOP_TO_BOTTOM, "bounce": MOTION_BOUNCE}
CODECS = {"h264": CODEC_H264, "hevc": CODEC_HEVC, "av1": CODEC_AV1}
# Loudness --normalize uses without a value, the level of the default preset in the GUI
DEFAULT_NORMALIZE_LUFS = -14.0

EXAMPLES = """
examples:
  main.py raw_videos
  main.py clip1.mp4 clip2.mov -w logo.png -o out --opacity 50
  main.py raw_videos --motion top-to-bottom --motion bounce --start-position random
  main.py raw_videos --codec hevc --gpu --normalize -16

Without any arguments, main.py opens the window of the program.
"""


def number(name, max_value, allow_zero=False):
    # Type of an option taking a number up to max_value, checked the same way as in the window
    def parse(text):
        try:
            return parse_field(text, name, max_value, allow_zero)
        except InvalidInput as e:
            raise argparse.ArgumentTypeError(str(e))
    return parse


def number_or_random(name, max_value):
    # Like number(), from 0, or "random" (None) for a random value for each video
    def parse(text):
        return None if text.lower() == "random" else number(name, max_value, allow_zero=True)(text)
    return parse


def lufs(text):
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"--normalize must be a loudness in LUFS, e.g. -14, not {text!r}.")
    if value >= 0:
        raise argparse.ArgumentTypeError("--normalize must be below 0 LUFS, e.g. -14.")
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Adds a moving watermark to videos.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="+", metavar="VIDEO_OR_FOLDER",
                        help="videos, or folders whose videos (not in subfolders) are watermarked")
    parser.add_argument("-o", "--output", default="watermarked_videos", metavar="FOLDER",
                        help="folder for the watermarked videos (default: %(default)s)")
    parser.add_argument("-w", "--watermark", default="watermark.png", metavar="IMAGE",
                        help="watermark image (default: %(default)s)")

    look = parser.add_argument_group("watermark")
    look.add_argument("--width", type=number("--width", MAX_PERCENT), default=50, metavar="PERCENT",
                      help="width, %% of the video width (default: %(default)s)")
    look.add_argument("--height", type=number("--height", MAX_PERCENT), metavar="PERCENT",
                      help="height, %% of the video height (default: kept from the width and the image)")
    look.add_argument("--opacity", type=number("--opacity", MAX_PERCENT), default=33, metavar="PERCENT",
                      help="opacity, %% (default: %(default)s)")

    motion = parser.add_argument_group("motion")
    motion.add_argument("--motion", action="append", choices=list(MOTIONS),
                        help="how the watermark moves (default: top-to-bottom); give it several times "
                             "to mix motions: the videos take them in turn, in the order given")
    motion.add_argument("--random-motion", action="store_true",
                        help="each video takes a random motion of the ones given with --motion")
    motion.add_argument("--travel-time", type=number("--travel-time", MAX_TRAVEL_TIME_SECONDS),
                        default=DEFAULT_TRAVEL_TIME_SECONDS, metavar="SECONDS",
                        help="top-to-bottom: seconds from top to bottom (default: %(default)s)")
    motion.add_argument("--position-change", type=number("--position-change", MAX_POSITION_CHANGE_SECONDS),
                        default=DEFAULT_POSITION_CHANGE_SECONDS, metavar="SECONDS",
                        help="top-to-bottom: seconds between horizontal jumps (default: %(default)s)")
    motion.add_argument("--bounce-speed", type=number("--bounce-speed", MAX_BOUNCE_SPEED_PERCENT),
                        default=DEFAULT_BOUNCE_SPEED_PERCENT, metavar="PERCENT",
                        help="bounce: speed, %% of the video height per second (default: %(default)s)")
    motion.add_argument("--start-position", type=number_or_random("--start-position", MAX_PERCENT),
                        default=0, metavar="PERCENT|random",
                        help="vertical start, %% from the top, or random for each video (default: 0)")
    motion.add_argument("--horizontal-start", type=number_or_random("--horizontal-start", MAX_PERCENT),
                        default=None, metavar="PERCENT|random",
                        help="bounce: horizontal start, %% from the left, or random for each video (default: random)")

    encoding = parser.add_argument_group("encoding")
    encoding.add_argument("--codec", choices=list(CODECS), default="h264",
                          help="video codec (default: %(default)s)")
    encoding.add_argument("--gpu", action="store_true",
                          help="encode with the video card if it can (faster, bigger files)")
    quality = encoding.add_mutually_exclusive_group()
    quality.add_argument("--crf", type=number("--crf", MAX_CRF), metavar="CRF",
                         help=f"constant quality, lower = better (default: {RECOMMENDED_CRF})")
    quality.add_argument("--bitrate", type=number("--bitrate", MAX_BITRATE_KBPS), metavar="KBPS",
                         help="video bitrate in kb/s instead of constant quality")
    quality.add_argument("--original-bitrate", action="store_true",
                         help="the bitrate of each original video instead of constant quality")
    encoding.add_argument("--qp", type=number("--qp", MAX_GPU_QP), metavar="QP",
                          help="with --gpu: constant quality on the scale of the video card encoder "
                               "(0-51, AV1: 0-255) instead of the CRF")
    encoding.add_argument("--normalize", type=lufs, nargs="?", const=DEFAULT_NORMALIZE_LUFS, metavar="LUFS",
                          help=f"normalize the audio loudness (default level: {DEFAULT_NORMALIZE_LUFS:g}; "
                               f"presets: {', '.join(f'{v:g}' for v in sorted(set(LOUDNESS_PRESETS.values())))})")
    return parser


def collect_videos(parser, inputs):
    # Videos among the inputs and right in the folders among them, each once, by name
    videos = {}
    for path in inputs:
        if os.path.isdir(path):
            found = find_videos(path)
            if not found:
                print(f"No videos in {path}", file=sys.stderr)
        elif is_video_file(path):
            found = [path]
        elif os.path.exists(path):
            parser.error(f"not a video: {path}")
        else:
            parser.error(f"not found: {path}")
        for video in found:
            videos.setdefault(os.path.normcase(os.path.realpath(video)), video)
    if not videos:
        parser.error("no videos to watermark")
    return sort_videos(videos.values())


def get_motions(args):
    # Motion settings for process_videos(), the same options for every motion that uses them
    motions = []
    for name in dict.fromkeys(args.motion or ["top-to-bottom"]):
        motion = MOTIONS[name]
        if motion == MOTION_TOP_TO_BOTTOM:
            motions.append({
                "motion": motion,
                "travel_time_seconds": args.travel_time,
                "start_position_percent": args.start_position,
                "position_change_seconds": args.position_change,
            })
        else:
            motions.append({
                "motion": motion,
                "bounce_speed_percent": args.bounce_speed,
                "start_position_percent": args.start_position,
                "horizontal_start_percent": args.horizontal_start,
            })
    return motions


def run(argv):
    # Watermarks the videos given on the command line, without the window
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.qp is not None and not args.gpu:
        parser.error("--qp needs --gpu")
    if not os.path.isfile(args.watermark):
        parser.error(f"watermark image not found: {args.watermark}")
    videos = collect_videos(parser, args.inputs)

    custom_bitrate = args.bitrate is not None
    use_crf = not custom_bitrate and not args.original_bitrate
    process_videos(
        videos,
        args.output,
        args.watermark,
        width_percent=args.width,
        height_percent=args.height,
        opacity_percent=args.opacity,
        motions=get_motions(args),
        random_motion_order=args.random_motion,
        # The CRF is also needed with a video card: the CPU takes over the videos it can't encode
        crf=(args.crf if args.crf is not None else RECOMMENDED_CRF) if use_crf else None,
        qp=args.qp if use_crf else None,
        bitrate_kbps=args.bitrate,
        target_lufs=args.normalize,
        use_gpu=args.gpu,
        codec=CODECS[args.codec],
    )
