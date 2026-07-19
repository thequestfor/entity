import sounddevice as sd
import torch
import numpy as np
import tempfile
import soundfile as sf
import speech
from collections import deque
from faster_whisper import WhisperModel

from vad import speech_event, reset_vad


model = None


def get_model():
    global model

    if model is None:
        print("Loading Whisper...")
        model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )

    return model


def listen_until_silence():

    print("Listening for command...")
    speech.say("GO AHEAD")
    reset_vad()

    samplerate = 16000
    chunk_size = 512

    audio_chunks = []

    # ~0.5 seconds of audio before VAD triggers
    pre_roll = deque(maxlen=15)

    speaking = False


    with sd.InputStream(
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        blocksize=chunk_size
    ) as stream:

        while True:

            chunk, _ = stream.read(chunk_size)

            chunk = chunk.flatten()

            pre_roll.append(chunk.copy())


            tensor = torch.from_numpy(chunk)

            event = speech_event(tensor)


            if event:

                print("VAD EVENT:", event)


                if "start" in event:

                    print("Speech started")

                    speaking = True

                    # Add audio before VAD detected speech
                    audio_chunks.extend(pre_roll)


                elif "end" in event:

                    print("Speech ended")

                    break


            if speaking:

                audio_chunks.append(chunk.copy())


    if not audio_chunks:

        print("No speech captured")

        return ""


    audio = np.concatenate(audio_chunks)


    print(
        "Captured:",
        len(audio) / samplerate,
        "seconds",
        "min:",
        audio.min(),
        "max:",
        audio.max()
    )


    filename = "debug_command.wav"

    sf.write(
        filename,
        audio,
        samplerate
    )

    print("Saved:", filename)


    with tempfile.NamedTemporaryFile(
        suffix=".wav"
    ) as f:


        sf.write(
            f.name,
            audio,
            samplerate
        )


        whisper = get_model()


        print("Transcribing...")


        segments, info = whisper.transcribe(
            f.name,
            vad_filter=True,
            condition_on_previous_text=False
        )


        text = ""


        for segment in segments:

            print("SEGMENT:", segment.text)

            text += segment.text



    print("Final text:", text)

    return text.strip()