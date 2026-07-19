class SentenceBuffer:

    def __init__(self):
        self.buffer = ""

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
