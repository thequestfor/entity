from pathlib import Path

from agent.memory import Memory
from agent.brain.prompts import entity_prompt
from agent.brain.llm import think
from agent.models.base import ModelUnavailable
from agent.response_quality import needs_user_facing_rewrite



class Brain:

    def __init__(self, memory=None, generator=None):

        self.memory = memory or Memory()
        self.generator = generator or think

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

        full_response = self._generate(
            prompt,
            command,
            on_escalation
        )

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
