# Starts the window of the program: uv run gui.py. The window itself is in the ui package
from ui.app import UniversalWatermark, run

__all__ = ["UniversalWatermark", "run"]

if __name__ == "__main__":
    run()
