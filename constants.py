import re

# A number with at most 2 decimal places, using "." or "," as the separator;
# incomplete input like "", "0" or "12." is allowed while typing
PERCENT_INPUT_RE = re.compile(r"(0|[1-9][0-9]*)?([.,][0-9]{0,2})?")

MAX_PERCENT = 100

# Text color of locked fields (light theme, dark theme)
DISABLED_TEXT_COLOR = ("gray55", "gray50")

# Step of the arrow buttons, Up/Down keys and mouse wheel
PERCENT_STEP = 1
