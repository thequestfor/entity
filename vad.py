import torch
from silero_vad import load_silero_vad, VADIterator


model = load_silero_vad()

vad_iterator = None


def reset_vad():
    global vad_iterator

    vad_iterator = VADIterator(
        model,
        threshold=0.5,
        sampling_rate=16000,
        min_silence_duration_ms=1000
    )


reset_vad()


def speech_event(audio):

    if not isinstance(audio, torch.Tensor):
        audio = torch.from_numpy(audio)

    return vad_iterator(audio)