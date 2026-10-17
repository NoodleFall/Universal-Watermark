from moviepy.video.io.ffmpeg_reader import ffmpeg_parse_infos


def get_video_info(video_path):
    """
    Reads the video parameters without decoding it: duration, size,
    bitrates and audio info, as reported by ffmpeg.
    """
    infos = ffmpeg_parse_infos(video_path)
    width, height = infos["video_size"]
    # ffmpeg rotates phone videos while decoding, so the sides swap for 90/270 degrees
    if abs(infos.get("video_rotation", 0)) in (90, 270):
        width, height = height, width
    return {
        "duration": infos["duration"],
        "width": width,
        "height": height,
        "video_bitrate": infos.get("video_bitrate"),
        "total_bitrate": infos.get("bitrate"),
        "audio_found": infos.get("audio_found", False),
        "audio_bitrate": infos.get("audio_bitrate"),
        "audio_fps": infos.get("audio_fps"),
    }
