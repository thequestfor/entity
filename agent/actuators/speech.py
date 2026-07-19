from agent.audio.activity import speaking


class SpeechActuator:
    action_type = "speak"

    def can_handle(self, action):
        return action.type == self.action_type

    def execute(self, action):
        import speech

        text = action.payload.get("text", "")
        stream = action.payload.get("stream")

        with speaking():
            if stream is not None:
                full_response = ""

                for token in stream:
                    full_response += token
                    speech.stream_text(token)

                speech.flush()
                speech.wait()

                return full_response

            if text:
                speech.say(text)

        return text
