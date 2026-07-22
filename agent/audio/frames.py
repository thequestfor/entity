import numpy as np


class WakeFrameBuffer:
    def __init__(self, frame_size=1280):
        self.frame_size = frame_size
        self.samples = np.empty(0, dtype=np.int16)

    def add(self, samples):
        samples = np.asarray(samples, dtype=np.int16).reshape(-1)

        if samples.size:
            self.samples = np.concatenate((self.samples, samples))

        frames = []

        while self.samples.size >= self.frame_size:
            frames.append(self.samples[:self.frame_size])
            self.samples = self.samples[self.frame_size:]

        return frames

    def clear(self):
        self.samples = np.empty(0, dtype=np.int16)
