import os

from constants import VIDEO_EXTENSIONS


def is_video_file(path):
    # Videos are told by their extension, compared case-insensitively
    return os.path.isfile(path) and path.lower().endswith(VIDEO_EXTENSIONS)


def find_videos(folder):
    # Videos right in the folder, not in its subfolders, as full paths
    return [
        path for path in (os.path.join(folder, name) for name in os.listdir(folder)) if is_video_file(path)
    ]


def sort_videos(video_paths):
    # By file name, so the motions go in turn in a predictable order; videos with the same name
    # from different folders by their folder
    return sorted(video_paths, key=lambda path: (os.path.basename(path).lower(), path.lower()))
