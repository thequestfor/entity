print("before whisper")

from faster_whisper import WhisperModel

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="float32"
)

print("after whisper")