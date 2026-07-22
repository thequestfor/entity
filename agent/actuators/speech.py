from agent.audio.activity import speaking, speech_output_listener


class SpeechActuator:
    action_type = "speak"

    def __init__(self, on_activity=None):
        self.on_activity = on_activity

    def can_handle(self, action):
        return action.type == self.action_type

    def execute(self, action):
        import speech

        text = action.payload.get("text", "")
        stream = action.payload.get("stream")
        phrased_stream = bool(action.payload.get("phrased_stream"))

        with speaking(), speech_output_listener(self.on_activity):
            if stream is not None:
                response_parts = []

                try:
                    for token in stream:
                        response_parts.append(str(token))
                        if phrased_stream:
                            speech.stream_phrase(token)
                        else:
                            speech.stream_text(token)
                finally:
                    if not phrased_stream:
                        speech.flush()
                    speech.wait()

                full_response = (
                    " ".join(part.strip() for part in response_parts).strip()
                    if phrased_stream
                    else "".join(response_parts)
                )
                return full_response

            if text:
                speech.say(text)

        return text
