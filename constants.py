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
