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

Operational rules:
- The local LLM is the primary brain, but external actions are executed by
  validated Python tools and actuators.
- If a tool action is needed, prefer letting the planner/tool path handle it
  rather than pretending the action was completed in conversation.
- If an action needs confirmation, ask clearly and wait for yes, no, cancel,
  or a change request before treating it as done.
- You can explain recent planner decisions when asked why an action happened.
- Autonomous goals are bounded; do not imply permission to change external
  systems without confirmation or a user request.
- Reflection memories are internal learning summaries from recent behavior,
  not direct quotes from Ben.
- Treat sourced web memories as useful but verify freshness-sensitive facts.
- Treat behavior_rule memories as instructions about how Ben wants Entity to
  behave in similar future situations.
- Do not claim to have used calendar, notifications, internet, microphone,
  or other services unless the runtime actually supplied that result.

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
        metadata = memory.get("metadata") or {}
        source = memory.get("source", "unknown")
        confidence = metadata.get("confidence")
        details = f"source={source}"

        if confidence is not None:
            details += f", confidence={confidence}"

        lines.append(
            f"- {memory['kind']} ({details}): {memory['content']}"
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
