import re

APP_NAME = "Universal Watermark"

# A number with at most 2 decimal places, using "." or "," as the separator;
# incomplete input like "", "0" or "12." is allowed while typing
NUMBER_INPUT_RE = re.compile(r"(0|[1-9][0-9]*)?([.,][0-9]{0,2})?")

MAX_PERCENT = 100

# Highest custom video bitrate, in kbit/s (200 Mbit/s)
MAX_BITRATE_KBPS = 200000

# Longest time the watermark may take to travel from the top to the bottom
MAX_TRAVEL_TIME_SECONDS = 3600

# Text color of locked fields (light theme, dark theme)
DISABLED_TEXT_COLOR = ("gray55", "gray50")

# Step of the arrow buttons, Up/Down keys and mouse wheel
NUMBER_STEP = 1

# Extensions of the videos to process, compared case-insensitively
VIDEO_EXTENSIONS = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".wmv", ".flv", ".ts")

# Containers that can't hold H.264 video with AAC audio are saved with another extension
OUTPUT_EXTENSION_OVERRIDES = {".webm": ".mp4"}

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

# Preset selected by default: -14 LUFS, the level the program has always used
DEFAULT_LOUDNESS_PRESET = "YouTube / Spotify / Amazon Music / Tidal (-14 LUFS)"
