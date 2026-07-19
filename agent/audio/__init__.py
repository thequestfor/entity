class Microphone:

    def __init__(self):

        self.samplerate = 16000
        self.blocksize = 512

        self.running = False

        self.buffer = deque(
            maxlen=50
        )

        self.audio_event = threading.Event()

        self.wake_event = threading.Event()

        self.stream = None

        self.model = Model(
            inference_framework="onnx"
        )

        # ADD THESE HERE
        self.mode = "wake"
        self.cooldown = 0
