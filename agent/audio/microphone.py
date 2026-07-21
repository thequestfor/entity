import threading
import tempfile
from collections import deque
from queue import Queue, Empty
import time

import numpy as np
import sounddevice as sd
import soundfile as sf
import torch

from faster_whisper import WhisperModel
from openwakeword.model import Model

from agent.audio.activity import is_speaking
from vad import speech_event, reset_vad


class Microphone:

    def __init__(self):

        self.samplerate = 16000
        self.blocksize = 512

        self.running = False

        # Last ~1.5 seconds of audio
        self.preroll = deque(maxlen=50)

        # Live audio from callback
        self.live_audio = Queue()

        self.wake_event = threading.Event()

        self.state = "idle"
        self.wake_cooldown_until = 0

        print("Loading Wake Word...")
        self.wake_model = self._new_wake_model()

        self.whisper = None


    def start(self):

        if self.running:
            return

        self.running = True

        threading.Thread(
            target=self._listen,
            daemon=True
        ).start()

        print("Microphone started")


    def _listen(self):

        with sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            blocksize=self.blocksize,
            callback=self._callback
        ):

            while self.running:
                sd.sleep(100)


    def _callback(
        self,
        indata,
        frames,
        time_info,
        status
    ):

        if is_speaking():
            return

        audio = np.squeeze(indata.copy())

        if self.state == "command":
            self.live_audio.put(audio)
            return

        if self.state != "wake":
            return

        if time.time() < self.wake_cooldown_until:
            return

        pcm = (
            audio * 32767
        ).astype(np.int16)

        prediction = self.wake_model.predict(pcm)

        for name, score in prediction.items():

            if score > 0.8:

                print("Wake:", name)

                self._clear_audio()
                self.state = "command"
                self.wake_cooldown_until = time.time() + 0.35

                self.wake_event.set()

                break


    def wait_for_wake(self):

        print("Waiting for wake word...")

        while is_speaking():
            time.sleep(0.05)

        self.wake_event.clear()
        self.preroll.clear()
        self._clear_audio()

        self.state = "wake"

        self.wake_event.wait()

        self.wake_event.clear()
        self.state = "command"
        self._reset_wake_model()

        reset_vad()

        self.preroll.clear()


    def listen(self):

        print("Listening...")

        if is_speaking():
            self.state = "idle"
            return ""

        speaking = False

        audio_chunks = []
        started_at = time.time()
        no_speech_timeout = 5
        max_command_seconds = 30

        while True:

            try:
                chunk = self.live_audio.get(timeout=0.5)
            except Empty:
                elapsed = time.time() - started_at

                if not speaking and elapsed >= no_speech_timeout:
                    self.state = "idle"
                    return ""

                if elapsed >= max_command_seconds:
                    break

                continue

            self.preroll.append(chunk)
            event = speech_event(
                torch.from_numpy(chunk)
            )

            if event:

                print("VAD:", event)

                if "start" in event:

                    if not speaking:

                        speaking = True

                        # Include audio before speech started
                        audio_chunks.extend(
                            list(self.preroll)
                        )

                elif "end" in event:

                    break

            if speaking:

                audio_chunks.append(chunk)

        self.state = "idle"

        if not audio_chunks:
            return ""

        audio = np.concatenate(audio_chunks)

        return self.transcribe(audio)


    def transcribe(self, audio):

        if self.whisper is None:

            print("Loading Whisper...")

            self.whisper = WhisperModel(
                "base",
                device="cpu",
                compute_type="int8"
            )

        with tempfile.NamedTemporaryFile(
            suffix=".wav"
        ) as f:

            sf.write(
                f.name,
                audio,
                self.samplerate
            )

            segments, _ = self.whisper.transcribe(
                f.name,
                vad_filter=False,
                condition_on_previous_text=False
            )

            text = ""

            for segment in segments:

                print("SEGMENT:", segment.text)

                text += segment.text

        print("Final:", text.strip())

        return text.strip()


    def stop(self):

        self.running = False

    def _clear_audio(self):
        while True:
            try:
                self.live_audio.get_nowait()
            except Empty:
                break

    def _new_wake_model(self):
        return Model()

    def _reset_wake_model(self):
        reset = getattr(self.wake_model, "reset", None)

        if callable(reset):
            reset()
            return

        self.wake_model = self._new_wake_model()
