import re

APP_NAME = "Universal Watermark"

# A number with at most 2 decimal places, using "." or "," as the separator;
# incomplete input like "", "0" or "12." is allowed while typing
NUMBER_INPUT_RE = re.compile(r"(0|[1-9][0-9]*)?([.,][0-9]{0,2})?")

MAX_PERCENT = 100

# Video quality modes: constant quality (CRF), the bitrate of the original, or a custom bitrate
QUALITY_CRF = "Same quality (CRF)"
QUALITY_ORIGINAL_BITRATE = "Same bitrate as original"
QUALITY_CUSTOM_BITRATE = "Custom bitrate"
VIDEO_QUALITY_MODES = (QUALITY_CRF, QUALITY_ORIGINAL_BITRATE, QUALITY_CUSTOM_BITRATE)
# Name of QUALITY_CRF in the menu while a video card encodes: they have a QP instead of a CRF
QUALITY_GPU_QP = "Same quality (QP)"

# CRF: lower is better quality and bigger files; 23 is x264's default balance of quality and size
RECOMMENDED_CRF = 23
MAX_CRF = 51

# Highest QP of video card encoders: 51 for H.264 and HEVC, 255 for the AV1 quality index
MAX_GPU_QP = 255

# Highest custom video bitrate, in kbit/s (200 Mbit/s)
MAX_BITRATE_KBPS = 200000

# Lowest audio bitrate, in kbit/s: regular AAC needs about this much for full-range stereo
MIN_AUDIO_BITRATE_KBPS = 128

# How often the watermark jumps to a new random horizontal position, in seconds: by default and at most
DEFAULT_POSITION_CHANGE_SECONDS = 5
MAX_POSITION_CHANGE_SECONDS = 3600

# How the watermark moves: from the top to the bottom with random horizontal jumps,
# or in straight lines bouncing off the edges of the video, like the DVD screensaver
MOTION_TOP_TO_BOTTOM = "Top to bottom, horizontal jumps"
MOTION_BOUNCE = "Bounce off the edges (DVD)"
# Mixes the motions above over the videos, each with the same settings as when chosen on its own
MOTION_CUSTOM = "Custom (mix motions)"
WATERMARK_MOTIONS = (MOTION_TOP_TO_BOTTOM, MOTION_BOUNCE, MOTION_CUSTOM)

# Motions the custom motion mixes, in their default order, with the names their settings
# are saved under, e.g. "bounce_start_position_percent" and "custom_bounce_use"
MOTION_KEYS = {MOTION_TOP_TO_BOTTOM: "top_to_bottom", MOTION_BOUNCE: "bounce"}

# How the custom motion picks the motion of each video: in turn by their numbers, or at random
CUSTOM_ORDER_IN_TURN = "In turn, by number"
CUSTOM_ORDER_RANDOM = "Random for each video"
CUSTOM_ORDERS = (CUSTOM_ORDER_IN_TURN, CUSTOM_ORDER_RANDOM)

# Time for the watermark to travel from the top to the bottom by default, in seconds
DEFAULT_TRAVEL_TIME_SECONDS = 30

# Speed of the bouncing watermark, as a percentage of the video height per second: by default and at most
DEFAULT_BOUNCE_SPEED_PERCENT = 10
MAX_BOUNCE_SPEED_PERCENT = 1000

# Stages of processing one video, in order; their progress is shown in the console and the GUI
STAGE_MEASURING_LOUDNESS = "Measuring loudness"
STAGE_NORMALIZING_AUDIO = "Normalizing audio"
STAGE_ENCODING_VIDEO = "Encoding video"
VIDEO_STAGES = (STAGE_MEASURING_LOUDNESS, STAGE_NORMALIZING_AUDIO, STAGE_ENCODING_VIDEO)
# Shown in gray in place of the stage while no video is being processed
VIDEO_STAGE_PLACEHOLDER = "[0/0] Video stage"

# Marks temporary files next to the output video, e.g. "watermarked_aTEMP_UW_loudnorm.wav"
TEMP_FILE_MARKER = "TEMP_UW_"

# Longest time the watermark may take to travel from the top to the bottom
MAX_TRAVEL_TIME_SECONDS = 3600

# Largest part of the screen height the window opens with; taller settings scroll
MAX_WINDOW_SCREEN_SHARE = 0.85
# Lowest height of the scrollable settings when the window is made shorter, in pixels
MIN_SETTINGS_HEIGHT = 120

# Step of the arrows of number fields, Up/Down keys and mouse wheel
NUMBER_STEP = 1

# Extensions of the videos to process, compared case-insensitively
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".wmv", ".flv", ".ts")

# Containers that can't hold H.264 video with AAC audio are saved with another extension
OUTPUT_EXTENSION_OVERRIDES = {".webm": ".mp4"}

# Video codecs to encode with
CODEC_H264 = "H.264 (most compatible)"
CODEC_HEVC = "HEVC / H.265 (smaller files)"
CODEC_AV1 = "AV1 (smallest files, slow on CPU)"
VIDEO_CODECS = (CODEC_H264, CODEC_HEVC, CODEC_AV1)

# Containers that can hold HEVC and AV1 video with AAC audio; other videos are saved as .mp4
CODEC_CONTAINERS = {
    CODEC_HEVC: (".mp4", ".mkv", ".mov", ".m4v", ".ts"),
    CODEC_AV1: (".mp4", ".mkv", ".mov", ".m4v"),
}

# Audio normalization targets of popular platforms and standards, in LUFS
# (platforms with the same target share one preset)
LOUDNESS_PRESETS = {
    "Spotify Loud (-11 LUFS)": -11.0,
    "YouTube / Spotify / Amazon Music / Tidal (-14 LUFS)": -14.0,
    "Deezer (-15 LUFS)": -15.0,
    "Apple Music / Podcasts (-16 LUFS)": -16.0,
    "Spotify Quiet (-19 LUFS)": -19.0,
    "Broadcast EBU R128 (-23 LUFS)": -23.0,
    "Broadcast ATSC A/85 (-24 LUFS)": -24.0,
}

# Highest peak level after normalization, in dBTP; louder peaks are smoothly limited
LOUDNESS_TRUE_PEAK_DB = -1.0

# Allowed loudness range, in LU; the maximum keeps the original dynamics untouched
LOUDNESS_RANGE_LU = 50

# Preset selected by default: -14 LUFS, the level the program has always used
DEFAULT_LOUDNESS_PRESET = "YouTube / Spotify / Amazon Music / Tidal (-14 LUFS)"
