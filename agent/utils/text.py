import re


def sanitize_tts(text: str) -> str:
    if not text:
        return ""

    # Remove escaped characters
    text = text.replace("\\n", " ")
    text = text.replace("\\t", " ")
    text = text.replace("\\r", " ")

    # Remove actual newlines/tabs
    text = text.replace("\n", " ")
    text = text.replace("\t", " ")
    text = text.replace("\r", " ")

    # Remove markdown
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = text.replace("*", "")
    text = text.replace("#", "")

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def chunk_tts(text: str, max_length: int = 180) -> list[str]:
    """
    Split text into speech-sized chunks.
    Prefer splitting on sentence boundaries,
    then commas,
    then spaces.
    """

    text = sanitize_tts(text)

    if len(text) <= max_length:
        return [text]

    chunks = []

    # First split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)

    current = ""

    for sentence in sentences:

        # Sentence fits in current chunk
        if len(current) + len(sentence) + 1 <= max_length:
            current += (" " if current else "") + sentence
            continue

        # Save previous chunk
        if current:
            chunks.append(current.strip())

        # Sentence itself is too long
        if len(sentence) > max_length:

            while len(sentence) > max_length:

                split = sentence.rfind(",", 0, max_length)

                if split == -1:
                    split = sentence.rfind(" ", 0, max_length)

                if split == -1:
                    split = max_length

                chunks.append(sentence[:split].strip())
                sentence = sentence[split:].strip()

            current = sentence

        else:
            current = sentence

    if current:
        chunks.append(current.strip())

    return chunks