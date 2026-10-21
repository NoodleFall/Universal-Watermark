from constants import VIDEO_STAGES

# Width of the console progress bar, in characters
BAR_WIDTH = 30

# Width of the longest label with its step number, e.g. "[1/3] Measuring loudness:",
# so the progress bars of all stages line up
LABEL_WIDTH = len("[1/3] :") + max(len(stage) for stage in VIDEO_STAGES)

# Whether the last console line is an unfinished progress line
_line_open = False


def print_progress(label, percent):
    # Progress bar of the current step in the same console line, ending the line at 100%.
    # ASCII characters, so the bar prints in any console encoding (e.g. on Windows)
    global _line_open
    filled = BAR_WIDTH * percent // 100
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    print(f"\r{label + ':':<{LABEL_WIDTH}} [{bar}] {percent:3d}%", end="\n" if percent == 100 else "", flush=True)
    _line_open = percent < 100


def end_progress_line():
    # Ends an unfinished progress line, so the next message starts on a new line
    global _line_open
    if _line_open:
        print(flush=True)
        _line_open = False
