import numpy as np
from moviepy.audio.AudioClip import AudioClip


def normalize_audio_clip(audio_clip, target_lufs=-14.0, fps=44100):
    """
    Approximate normalization to a target loudness level in LUFS.
    Done via RMS (dBFS ≈ LUFS in most cases).

    target_lufs: target level, e.g. -14.0 (for streaming platforms).
    """
    if audio_clip is None:
        return None

    try:
        snd = audio_clip.to_soundarray(fps=fps)  # [samples, channels] or [samples]
    except Exception as e:
        print(f"Failed to read audio for normalization: {e}")
        return audio_clip

    if snd.size == 0:
        return audio_clip

    # Downmix to mono for loudness calculation
    if snd.ndim == 2:
        snd_mono = snd.mean(axis=1)
    else:
        snd_mono = snd

    # RMS
    rms = float(np.sqrt(np.mean(snd_mono ** 2)))
    if rms == 0:
        print("[Normalization] Complete silence, skipping")
        return audio_clip

    # dBFS ≈ LUFS
    current_lufs = 20 * np.log10(rms + 1e-12)

    gain_db = target_lufs - current_lufs
    # Convert dB → factor
    factor = 10 ** (gain_db / 20.0)

    # Limit boost/cut to reasonable bounds to avoid extreme results
    factor = float(np.clip(factor, 0.1, 10.0))

    print(f"[LUFS normalization] current ≈ {current_lufs:.2f} LUFS, target = {target_lufs:.2f} LUFS, gain = {gain_db:.2f} dB, factor = {factor:.3f}")

    snd_norm = snd * factor
    # Guard against amplitude clipping
    snd_norm = np.clip(snd_norm, -1.0, 1.0)

    def make_frame(t):
        t_arr = np.array(t, dtype=float)
        idx = (t_arr * fps).astype(int)
        idx = np.clip(idx, 0, snd_norm.shape[0] - 1)
        return snd_norm[idx]

    normalized_audio = AudioClip(make_frame, duration=audio_clip.duration, fps=fps)
    return normalized_audio
