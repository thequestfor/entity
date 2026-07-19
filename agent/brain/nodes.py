from pathlib import Path

from agent.memory import Memory
from agent.brain.prompts import entity_prompt
from agent.brain.llm import stream


memory = Memory()


identity = Path(
    "agent/identity.md"
).read_text()



def think_node(state):

    memories = memory.context_for(
        state["user_input"]
    )


    prompt = entity_prompt(
        identity,
        memories,
        state,
        state["user_input"]
    )


    full_response = ""


    for token in stream(prompt):

        print(
            "NODE TOKEN:",
            repr(token)
        )

        full_response += token


        yield {
            "response": token
        }


    memory.remember(
        "events",
        {
            "user": state["user_input"],
            "entity": full_response,
            "state": state
        }
    )
