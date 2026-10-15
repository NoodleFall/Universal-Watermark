import re

# A number with at most 2 decimal places, using "." or "," as the separator;
# incomplete input like "", "0" or "12." is allowed while typing
NUMBER_INPUT_RE = re.compile(r"(0|[1-9][0-9]*)?([.,][0-9]{0,2})?")

MAX_PERCENT = 100

# Longest time the watermark may take to travel from the top to the bottom
MAX_TRAVEL_TIME_SECONDS = 3600

# Text color of locked fields (light theme, dark theme)
DISABLED_TEXT_COLOR = ("gray55", "gray50")

# Step of the arrow buttons, Up/Down keys and mouse wheel
NUMBER_STEP = 1
