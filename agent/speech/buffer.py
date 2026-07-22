class SentenceBuffer:

    def __init__(self, soft_limit=110, hard_limit=190):
        self.buffer = ""
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit

    def add(self, token):

        self.buffer += token

        sentences = []

        while True:

            split = None

            for c in ".!?":

                pos = self.buffer.find(c)

                if pos != -1:

                    if split is None or pos < split:
                        split = pos

            if split is None and len(self.buffer) >= self.soft_limit:
                candidates = [
                    self.buffer.rfind(mark)
                    for mark in (",", ";", ":", "\n")
                ]
                split = max(candidates)

                if split < self.soft_limit // 2:
                    split = None

            if split is None and len(self.buffer) >= self.hard_limit:
                split = self.buffer.rfind(" ", 0, self.hard_limit + 1)

                if split < self.soft_limit // 2:
                    split = self.hard_limit - 1

            if split is None:
                break

            sentence = self.buffer[:split + 1].strip()

            self.buffer = self.buffer[split + 1:]

            if sentence:
                sentences.append(sentence)

        return sentences

    def flush(self):

        text = self.buffer.strip()

        self.buffer = ""

        if text:
            return [text]

        return []
