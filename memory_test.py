from tempfile import TemporaryDirectory
from pathlib import Path

from agent.memory import Memory
from agent.memory.store import MemoryStore


with TemporaryDirectory() as tmp:
    memory = Memory(
        MemoryStore(Path(tmp) / "memory.db")
    )

    memory.remember(
        "facts",
        "Ben created Entity."
    )

    memory.remember(
        "events",
        {
            "user": "Remember that I prefer concise answers.",
            "entity": "I will remember that."
        }
    )

    context = memory.context_for("concise answers")

    assert context["relevant_memories"]
    assert context["recent_conversations"]

    print(context)
