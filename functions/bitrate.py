from constants import MIN_AUDIO_BITRATE_KBPS


def get_audio_bitrate(info):
    # Audio bitrate to encode with in kbit/s: the original one, but not below
    # MIN_AUDIO_BITRATE_KBPS, or None if unknown.
    # Low bitrates of efficient codecs (e.g. 32 kbit/s HE-AAC from phones) sound
    # muffled when re-encoded as regular AAC at the same bitrate
    if not info["audio_found"] or not info["audio_bitrate"]:
        return None
    return max(info["audio_bitrate"], MIN_AUDIO_BITRATE_KBPS)


def get_video_bitrate(info):
    # Original video bitrate in kbit/s, or None if unknown
    if info["video_bitrate"]:
        return info["video_bitrate"]

    # Some containers (e.g. MKV, WebM) store only the bitrate of the whole file
    if info["total_bitrate"]:
        return max(info["total_bitrate"] - (info["audio_bitrate"] or 0), 1)
    return None
