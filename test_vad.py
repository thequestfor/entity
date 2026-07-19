import sounddevice as sd
import torch
from vad import contains_speech


print("Listening...")

audio = sd.rec(
    int(3 * 16000),
    samplerate=16000,
    channels=1,
    dtype="float32"
)

sd.wait()

audio = torch.from_numpy(audio.flatten())

print(
    "Speech detected:",
    contains_speech(audio)
)