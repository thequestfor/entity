import shutil
import subprocess
import threading
import time

import numpy as np
import soundfile as sf

from agent.audio.activity import emit_speech_output_activity


class _SpeechLevelMeter:
    def __init__(self, path, updates_per_second=25):
        self.period = 1 / updates_per_second
        self.levels = []
        self._stop = threading.Event()
        self._thread = None

        try:
            audio, samplerate = sf.read(
                str(path),
                always_2d=True,
                dtype="float32"
            )
            self.levels = _speech_levels(
                audio,
                samplerate,
                updates_per_second=updates_per_second
            )
        except (OSError, RuntimeError, ValueError):
            self.levels = []

    def start(self):
        if not self.levels:
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="entity-speech-meter",
            daemon=True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

        if self._thread:
            self._thread.join(timeout=0.25)
            self._thread = None

        emit_speech_output_activity(0)

    def _run(self):
        started = time.monotonic()

        try:
            for index, level in enumerate(self.levels):
                delay = started + index * self.period - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    return
                if self._stop.is_set():
                    return
                emit_speech_output_activity(level)
        finally:
            emit_speech_output_activity(0)


def _speech_levels(audio, samplerate, updates_per_second=25):
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0 or samplerate <= 0:
        return []

    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    window_size = max(1, int(samplerate / updates_per_second))
    rms_levels = []
    for start in range(0, len(samples), window_size):
        window = samples[start:start + window_size]
        rms_levels.append(float(np.sqrt(np.mean(np.square(window)))))

    if not rms_levels:
        return []

    reference = max(float(np.percentile(rms_levels, 90)), 0.025)
    noise_floor = min(reference * 0.12, 0.018)
    envelope = 0.0
    normalized_levels = []

    for rms in rms_levels:
        normalized = (rms - noise_floor) / max(reference - noise_floor, 1e-6)
        normalized = min(1.0, max(0.0, normalized))
        smoothing = 0.72 if normalized > envelope else 0.34
        envelope += (normalized - envelope) * smoothing
        normalized_levels.append(round(envelope, 4))

    return normalized_levels


def play_wav(path):
    meter = _SpeechLevelMeter(path)

    if shutil.which("afplay"):
        player = subprocess.Popen(
            [
                "afplay",
                str(path)
            ]
        )
        meter.start()
        try:
            if player.wait() != 0:
                raise subprocess.CalledProcessError(
                    player.returncode,
                    player.args
                )
        finally:
            meter.stop()
        return

    if shutil.which("aplay"):
        player = subprocess.Popen(
            [
                "aplay",
                str(path)
            ]
        )
        meter.start()
        try:
            if player.wait() != 0:
                raise subprocess.CalledProcessError(
                    player.returncode,
                    player.args
                )
        finally:
            meter.stop()
        return

    import sounddevice as sd

    audio, samplerate = sf.read(str(path))
    sd.play(audio, samplerate)
    meter.start()
    try:
        sd.wait()
    finally:
        meter.stop()
