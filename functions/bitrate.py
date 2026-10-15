def get_audio_bitrate(video):
    # Original audio bitrate in kbit/s, or None if unknown
    if video.audio is None:
        return None
    return video.audio.reader.bitrate or None


def get_video_bitrate(video, audio_bitrate_kbps):
    # Original video bitrate in kbit/s, or None if unknown
    if video.reader.bitrate:
        return video.reader.bitrate

    # Some containers (e.g. MKV, WebM) store only the bitrate of the whole file
    total_bitrate = video.reader.infos.get("bitrate")
    if total_bitrate:
        return max(total_bitrate - (audio_bitrate_kbps or 0), 1)
    return None
