from pathlib import Path

from agent.memory import Memory
from agent.brain.prompts import entity_prompt
from agent.brain.llm import stream as stream_llm
from agent.brain.llm import think
from agent.models.base import ModelUnavailable
from agent.response_quality import needs_user_facing_rewrite
from agent.speech.buffer import SentenceBuffer



class Brain:

    def __init__(self, memory=None, generator=None, stream_generator=None):

        self.memory = memory or Memory()
        self.generator = generator or think
        self.stream_generator = (
            stream_llm
            if generator is None and stream_generator is None
            else stream_generator
        )

        self.identity = Path(
            "agent/identity.md"
        ).read_text()


    def respond_stream(self, command, state, on_escalation=None):

        memories = self.memory.context_for(command)

        prompt = entity_prompt(
            self.identity,
            memories,
            state,
            command
        )

        if self.stream_generator is None:
            yield from self._respond_buffered(
                prompt,
                command,
                state,
                on_escalation
            )
            return

        yield from self._respond_live(
            prompt,
            command,
            state,
            on_escalation
        )

    def _respond_buffered(self, prompt, command, state, on_escalation):
        full_response = self._generate(prompt, command, on_escalation)

        if needs_user_facing_rewrite(full_response):
            full_response = self._generate(
                self._rewrite_prompt(command, full_response),
                command,
                on_escalation
            )

        if needs_user_facing_rewrite(full_response):
            full_response = (
                "I could not produce a reliable concise answer. "
                "Please try the question again."
            )

        yield full_response

        self._remember_response(command, full_response, state)

    def _respond_live(self, prompt, command, state, on_escalation):
        phrase_buffer = SentenceBuffer()
        draft_parts = []
        spoken_parts = []
        contaminated = False

        try:
            tokens = self.stream_generator(
                prompt,
                user_input=command,
                on_escalation=on_escalation
            )

            for token in tokens:
                token = str(token or "")

                if not token:
                    continue

                draft_parts.append(token)

                for phrase in phrase_buffer.add(token):
                    if needs_user_facing_rewrite(phrase):
                        contaminated = True
                        continue

                    if contaminated and not spoken_parts:
                        continue

                    spoken_parts.append(phrase)
                    yield self._speech_chunk(phrase, spoken_parts)

            for phrase in phrase_buffer.flush():
                if needs_user_facing_rewrite(phrase):
                    contaminated = True
                    continue

                if contaminated and not spoken_parts:
                    continue

                spoken_parts.append(phrase)
                yield self._speech_chunk(phrase, spoken_parts)
        except ModelUnavailable as exc:
            if not spoken_parts:
                outage = (
                    "I do not have an available language model. "
                    f"{exc}"
                )
                spoken_parts.append(outage)
                yield outage

        draft = "".join(draft_parts).strip()

        if contaminated and not spoken_parts:
            corrected = self._generate(
                self._rewrite_prompt(command, draft),
                command,
                on_escalation
            )

            if needs_user_facing_rewrite(corrected):
                corrected = (
                    "I could not produce a reliable concise answer. "
                    "Please try the question again."
                )

            spoken_parts.append(corrected)
            yield corrected

        full_response = " ".join(spoken_parts).strip()
        self._remember_response(command, full_response, state)

    def _speech_chunk(self, phrase, prior_phrases):
        if len(prior_phrases) == 1:
            return phrase

        return " " + phrase

    def _remember_response(self, command, full_response, state):
        if not full_response:
            return

        self.memory.remember(
            "events",
            {
                "user": command,
                "entity": full_response,
                "state": state
            }
        )

    def _generate(self, prompt, command, on_escalation):
        try:
            return self.generator(
                prompt,
                user_input=command,
                on_escalation=on_escalation
            ).strip()
        except ModelUnavailable as exc:
            return (
                "I do not have an available language model. "
                f"{exc}"
            )

    def _rewrite_prompt(self, command, draft):
        return (
            "Rewrite the draft as Entity's final user-facing answer. "
            "Answer the question immediately and concisely in natural "
            "language. Preserve useful facts, but remove all internal process "
            "narration, progress reports, status labels, readiness statements, "
            "memory claims, and unsupported claims of tool or internet use. "
            "Do not append offers to store the answer or explore other topics. "
            "State uncertain historical dates with precise qualification. "
            "Return only the answer, with no preamble.\n\n"
            f"User question: {command}\n"
            f"Draft: {draft}"
        )
