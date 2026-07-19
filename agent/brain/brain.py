from pathlib import Path

from agent.memory import Memory
from agent.brain.prompts import entity_prompt
from agent.brain.llm import stream



class Brain:

    def __init__(self):

        self.memory = Memory()

        self.identity = Path(
            "agent/identity.md"
        ).read_text()


    def respond_stream(self, command, state):

        memories = self.memory.context_for(command)

        prompt = entity_prompt(
            self.identity,
            memories,
            state,
            command
        )

        full_response = ""

        for token in stream(prompt):

            full_response += token

            yield token

        self.memory.remember(
            "events",
            {
                "user": command,
                "entity": full_response,
                "state": state
            }
        )
