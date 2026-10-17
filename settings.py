import json
import os
import re

from constants import (
    APP_NAME,
    CODEC_H264,
    DEFAULT_LOUDNESS_PRESET,
    LOUDNESS_PRESETS,
    QUALITY_CRF,
    QUALITY_CUSTOM_BITRATE,
    VIDEO_CODECS,
    VIDEO_QUALITY_MODES,
)


def get_settings_path():
    # %APPDATA% on Windows, ~/.config (or $XDG_CONFIG_HOME) elsewhere
    config_dir = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config_dir, APP_NAME, "settings.json")


def load_settings():
    try:
        with open(get_settings_path(), encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        # No saved settings yet, or the file is broken
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings):
    settings_path = get_settings_path()
    try:
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"Failed to save settings: {e}")


def find_loudness_preset(saved_name):
    # Saved preset name, or a preset with the same level if the name is outdated
    # (e.g. "Tidal (-14 LUFS)" from before presets were merged), or the default one
    if saved_name in LOUDNESS_PRESETS:
        return saved_name
    match = re.search(r"\((-?\d+(?:\.\d+)?) LUFS\)", str(saved_name))
    if match:
        for name, lufs in LOUDNESS_PRESETS.items():
            if lufs == float(match.group(1)):
                return name
    return DEFAULT_LOUDNESS_PRESET


def find_video_quality_mode(settings):
    # Saved video quality mode; settings from before the modes existed only have
    # "original_bitrate": a custom bitrate stays custom, otherwise use the default CRF mode
    mode = settings.get("video_quality")
    if mode in VIDEO_QUALITY_MODES:
        return mode
    if settings.get("original_bitrate") is False:
        return QUALITY_CUSTOM_BITRATE
    return QUALITY_CRF


def find_codec(saved_codec):
    # Saved video codec, or H.264 if none was saved yet
    return saved_codec if saved_codec in VIDEO_CODECS else CODEC_H264
