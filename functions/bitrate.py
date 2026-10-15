from constants import MIN_AUDIO_BITRATE_KBPS


def get_audio_bitrate(video):
    # Audio bitrate to encode with in kbit/s: the original one, but not below
    # MIN_AUDIO_BITRATE_KBPS, or None if unknown.
    # Low bitrates of efficient codecs (e.g. 32 kbit/s HE-AAC from phones) sound
    # muffled when re-encoded as regular AAC at the same bitrate
    if video.audio is None:
        return None
    original = video.audio.reader.bitrate
    if not original:
        return None
    return max(original, MIN_AUDIO_BITRATE_KBPS)


def get_video_bitrate(video, audio_bitrate_kbps):
    # Original video bitrate in kbit/s, or None if unknown
    if video.reader.bitrate:
        return video.reader.bitrate

    # Some containers (e.g. MKV, WebM) store only the bitrate of the whole file
    total_bitrate = video.reader.infos.get("bitrate")
    if total_bitrate:
        return max(total_bitrate - (audio_bitrate_kbps or 0), 1)
    return None
