from faster_whisper import WhisperModel
import time

print("starting")

start = time.time()

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("loaded in", time.time() - start)