def entity_prompt(
    identity,
    memories,
    state,
    user_input
):

    return f"""
You are Entity.

Identity:
{identity}

Relevant memory:
{format_memories(memories)}

State:
{state}

User:
{user_input}

Respond as Entity.
"""


def format_memories(memories):
    if not memories:
        return "No relevant memories yet."

    if isinstance(memories, str):
        return memories

    lines = []

    for memory in memories.get("relevant_memories", []):
        lines.append(
            f"- {memory['kind']}: {memory['content']}"
        )

    recent = memories.get("recent_conversations", [])

    if recent:
        lines.append("")
        lines.append("Recent conversation:")

    for item in recent:
        lines.append(f"- User: {item['user_text']}")
        lines.append(f"  Entity: {item['entity_text']}")

    if not lines:
        return "No relevant memories yet."

    return "\n".join(lines)
