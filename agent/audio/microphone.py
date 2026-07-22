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
from agent.audio.frames import WakeFrameBuffer
from vad import speech_event, reset_vad


class Microphone:

    def __init__(self, on_state=None):

        self.samplerate = 16000
        self.blocksize = 512

        self.running = False
        self.thread = None
        self.error = None
        self.on_state = on_state

        # Last ~1.5 seconds of audio
        self.preroll = deque(maxlen=50)

        # Live audio from callback
        self.live_audio = Queue()

        self.wake_event = threading.Event()
        self.wake_frames = WakeFrameBuffer()

        self.state = "idle"
        self.wake_cooldown_until = 0

        print("Loading Wake Word...")
        self.wake_model = self._new_wake_model()

        self.whisper = None


    def start(self):

        if self.running:
            return

        self.error = None
        self.wake_event.clear()
        self.running = True

        self.thread = threading.Thread(
            target=self._listen,
            daemon=True
        )
        self.thread.start()

        print("Microphone started")


    def _listen(self):

        try:
            with sd.InputStream(
                samplerate=self.samplerate,
                channels=1,
                dtype="float32",
                blocksize=self.blocksize,
                callback=self._callback
            ):
                while self.running:
                    sd.sleep(100)
        except Exception as exc:
            self.error = exc
            self.running = False
            self.wake_event.set()
            self._emit_state("error", component="microphone", message=str(exc))


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

        for wake_frame in self.wake_frames.add(pcm):
            if self._detect_wake(wake_frame):
                break

    def _detect_wake(self, pcm):
        prediction = self.wake_model.predict(pcm)

        for name, score in prediction.items():

            if score > 0.8:

                print("Wake:", name)

                self._clear_audio()
                self.wake_frames.clear()
                self.state = "command"
                self.wake_cooldown_until = time.time() + 0.35

                self.wake_event.set()

                return True

        return False


    def wait_for_wake(self):

        print("Waiting for wake word...")

        while self.running and is_speaking():
            time.sleep(0.05)

        if not self.running:
            return False

        self.wake_event.clear()
        self.preroll.clear()
        self._clear_audio()
        self.wake_frames.clear()

        self.state = "wake"

        while self.running and not self.wake_event.wait(timeout=0.25):
            pass

        if not self.running:
            self.state = "idle"
            return False

        self.wake_event.clear()
        self.state = "command"
        self._reset_wake_model()

        reset_vad()

        self.preroll.clear()
        return True


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

            if not self.running:
                self.state = "idle"
                return ""

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

        self._emit_state("transcribing")
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
        self.state = "idle"
        self.wake_event.set()

        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _clear_audio(self):
        while True:
            try:
                self.live_audio.get_nowait()
            except Empty:
                break

    def _new_wake_model(self):
        return Model()

    def _reset_wake_model(self):
        self.wake_model = self._new_wake_model()

    def _emit_state(self, state, **details):
        if self.on_state:
            self.on_state(state, **details)
