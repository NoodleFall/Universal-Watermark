# Starts the program: without arguments, the window (uv run main.py);
# with arguments, it watermarks the videos given in the console (uv run main.py --help)
import sys


def main():
    if len(sys.argv) > 1:
        # Imported here, so the console doesn't load the window's libraries and the other way round
        from cli import run as run_cli
        run_cli(sys.argv[1:])
    else:
        from ui.app import run as run_gui
        run_gui()


if __name__ == "__main__":
    main()
