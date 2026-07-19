from faster_whisper import WhisperModel

print("before")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("loaded")