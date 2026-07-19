from agent.events import Event
from agent.memory.semantic import MemoryEvaluator
from agent.memory.store import MemoryStore


class Memory:
    def __init__(self, store=None, evaluator=None):
        self.store = store or MemoryStore()
        self.evaluator = evaluator or MemoryEvaluator()

    def remember(self, category, item):
        if category == "events":
            if isinstance(item, dict) and "user" in item and "entity" in item:
                conversation_id = self.store.add_conversation(
                    item["user"],
                    item["entity"],
                    item.get("state")
                )

                candidate = self.evaluator.evaluate_text(
                    item["user"],
                    source="conversation",
                    state=item.get("state"),
                    context={
                        "entity_response": item["entity"]
                    }
                )

                self.store.add_candidate(
                    candidate,
                    metadata={
                        "conversation_id": conversation_id
                    }
                )

                return conversation_id

            if isinstance(item, Event):
                self.store.add_event(item)

                candidate = self.evaluator.evaluate_event(item)

                return self.store.add_candidate(
                    candidate,
                    metadata={
                        "event_id": item.id
                    }
                )

            return self.store.add_memory(
                "event",
                str(item),
                source="legacy",
                importance=2
            )

        return self.store.add_memory(
            self._normalize_kind(category),
            item if isinstance(item, str) else str(item),
            source="legacy",
            importance=self._importance_for(category)
        )

    def recall(self, category=None, query=None, limit=8):
        if query:
            return self.store.recall_context(query, limit=limit)

        if category:
            return self.store.list_memories(
                kind=self._normalize_kind(category),
                limit=limit
            )

        return {
            "facts": self.store.list_memories("fact", limit=limit),
            "preferences": self.store.list_memories(
                "preference",
                limit=limit
            ),
            "events": self.store.list_memories("event", limit=limit),
            "recent_conversations": self.store.recent_conversations(
                limit=limit
            )
        }

    def context_for(self, text, limit=8):
        return self.store.recall_context(text, limit=limit)

    def _normalize_kind(self, category):
        if category == "facts":
            return "fact"

        if category == "preferences":
            return "preference"

        if category == "events":
            return "event"

        return category

    def _importance_for(self, category):
        if category == "preferences":
            return 4

        if category == "facts":
            return 3

        return 1
