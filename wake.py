print("wake: start")

import openwakeword
print("wake: imported openwakeword")
import onnxruntime as ort

_old_session = ort.InferenceSession

def cpu_session(*args, **kwargs):
    kwargs["providers"] = ["CPUExecutionProvider"]
    return _old_session(*args, **kwargs)

ort.InferenceSession = cpu_session

from openwakeword.model import Model

import sounddevice as sd

import numpy as np

model = Model(
    inference_framework="onnx"
)


def wait_for_wake_word():

    global model

    print("Waiting for wake word...")

    with sd.InputStream(
        channels=1,
        samplerate=16000,
        dtype="int16",
        blocksize=1280
    ) as stream:

        while True:

            audio, overflow = stream.read(1280)

            audio = np.squeeze(audio)

            prediction = model.predict(audio)

            for key, value in prediction.items():

                if value > 0.8:
                    print("Wake detected:", key)

                    # reset internal state
                    model = Model(
                        inference_framework="onnx"
                    )

                    return