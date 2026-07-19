from openwakeword.model import Model
import numpy as np
import sounddevice as sd

model = Model(inference_framework="onnx")
for name, m in model.models.items():
    print(name, m.get_providers())
with sd.InputStream(
    samplerate=16000,
    channels=1,
    dtype="int16",
    blocksize=1280
) as stream:
    import time

    last = time.time()

    while True:
        audio, overflow = stream.read(1280)

        now = time.time()
        print("dt:", now - last)
        last = now