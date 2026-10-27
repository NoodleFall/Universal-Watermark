# Universal Watermark

Adds a moving watermark to videos: from the top to the bottom with random horizontal jumps,
bouncing off the edges like the DVD screensaver, or a mix of both. Works in a window or in the console.

## Running

Install [uv](https://docs.astral.sh/uv/), then in the project folder:

```
uv run main.py
```

Without arguments, `main.py` opens the window. With arguments, it works in the console (see below).

## Window

Add videos with "Add video" or by dropping files and folders on the window. They are processed
in the order shown, which can be sorted by name, dates, duration, file size or resolution.
Ctrl+Z undoes changes of the settings and of the list of videos; Ctrl+Shift+Z or Ctrl+Y redoes them.

## Console

```
uv run main.py VIDEO_OR_FOLDER [VIDEO_OR_FOLDER ...] [options]
```

Give any number of videos and folders. A folder adds the videos right in it, not in its subfolders.
The videos are processed in the order of their names. Each result is saved as `watermarked_<name>`
in the output folder; videos with the same name from different folders get `_2`, `_3`… at the end.

### Examples

```
# All the videos in the raw_videos folder, with watermark.png, into watermarked_videos
uv run main.py raw_videos

# Two videos with another image and output folder, a more visible watermark
uv run main.py clip1.mp4 clip2.mov -w logo.png -o out --opacity 50

# The DVD-like bouncing watermark, faster than by default
uv run main.py raw_videos --motion bounce --bounce-speed 20

# Both motions in turn (1st video top to bottom, 2nd bouncing, 3rd top to bottom…),
# each video starting at a random height
uv run main.py raw_videos --motion top-to-bottom --motion bounce --start-position random

# HEVC on the video card, with the audio normalized to -16 LUFS
uv run main.py raw_videos --codec hevc --gpu --normalize -16
```

### Options

Numbers can have up to two decimals, with `.` or `,`. Defaults are the same as in the window.

| Option | Meaning | Default |
| --- | --- | --- |
| `-o`, `--output FOLDER` | Folder for the watermarked videos; created if missing | `watermarked_videos` |
| `-w`, `--watermark IMAGE` | Watermark image (PNG with transparency works best) | `watermark.png` |
| **Watermark** | | |
| `--width PERCENT` | Width, % of the video width | `50` |
| `--height PERCENT` | Height, % of the video height | kept from the width and the image |
| `--opacity PERCENT` | Opacity, from almost invisible to 100 = opaque | `33` |
| **Motion** | | |
| `--motion top-to-bottom\|bounce` | How the watermark moves. Give it several times to mix motions: the videos take them in turn, in the order given | `top-to-bottom` |
| `--random-motion` | Each video takes a random motion of the ones given with `--motion` | off |
| `--travel-time SECONDS` | top-to-bottom: time from the top to the bottom | `30` |
| `--position-change SECONDS` | top-to-bottom: time between horizontal jumps | `5` |
| `--bounce-speed PERCENT` | bounce: speed, % of the video height per second | `10` |
| `--start-position PERCENT\|random` | Height at the start of each video, % from the top (0 = top, 100 = bottom), or `random` | `0` |
| `--horizontal-start PERCENT\|random` | bounce: position at the start, % from the left, or `random` | `random` |
| **Encoding** | | |
| `--codec h264\|hevc\|av1` | Video codec: `h264` plays everywhere, `hevc` and `av1` give smaller files | `h264` |
| `--gpu` | Encode on the video card if it can (faster, bigger files); otherwise the CPU is used | off |
| `--crf CRF` | Constant quality, 0–51, lower = better and bigger | `23` |
| `--bitrate KBPS` | Video bitrate in kb/s instead of constant quality | — |
| `--original-bitrate` | The bitrate of each original video instead of constant quality | — |
| `--qp QP` | With `--gpu`: constant quality on the video card's scale (0–51, AV1: 0–255) instead of the CRF | matches the CRF |
| `--normalize [LUFS]` | Normalize the audio loudness; without a value, to -14 LUFS (YouTube, Spotify) | off |

Only one of `--crf`, `--bitrate` and `--original-bitrate` can be given.
Common `--normalize` levels: -11 (Spotify Loud), -14 (YouTube, Spotify, Amazon Music, Tidal),
-15 (Deezer), -16 (Apple Music, podcasts), -19 (Spotify Quiet), -23 (EBU R128), -24 (ATSC A/85).
Put the videos before `--normalize` when it has no value, otherwise the next argument is read as the level.

`uv run main.py --help` shows the full list.

Supported videos: mp4, avi, mov, mkv, webm, m4v, wmv, flv, ts.
