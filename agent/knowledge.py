import re

from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.store import IntelligenceStore
from agent.memory.store import MemoryStore


class LearningDigest:
    """Explain retained learning without inventing model-internal knowledge."""

    def __init__(self, memory_store=None, intelligence_store=None):
        self.memory_store = memory_store or MemoryStore()
        self.intelligence_store = intelligence_store
        if self.intelligence_store is None:
            config = IntelligenceConfig.from_env()
            if config.enabled:
                self.intelligence_store = IntelligenceStore(config.database_path)

    def build(self, topic=""):
        topic = str(topic or "").strip()
        sections = []
        memories = self._memories(topic)
        if memories:
            sections.append(
                "Durable memory: "
                + " ".join(self._sentence(item["content"]) for item in memories)
            )

        sections.extend(self._public_learning(topic))
        if not sections:
            subject = f" about {topic}" if topic else ""
            return (
                f"I do not have retained learning{subject} yet. "
                "I distinguish that from information a language model only "
                "knows temporarily."
            )

        opening = (
            f"Here is what I have retained about {topic}."
            if topic else
            "Here is what I have retained and learned so far."
        )
        return " ".join([
            opening,
            *sections,
            "Public-world conclusions are evidence-weighted and provisional."
        ])

    def context_for(self, query, limit=5):
        """Return concise evidence relevant to ordinary reasoning."""
        if self.intelligence_store is None:
            return []

        terms = self._context_terms(query)
        if not terms:
            return []

        candidates = []
        for item in self.intelligence_store.list_situations(limit=100):
            score = self._overlap_score(item, terms)
            if score:
                candidates.append((score, "situation", item))
        for item in self.intelligence_store.list_documents(limit=150):
            if item.get("category") == "prediction-market":
                continue
            score = self._overlap_score(item, terms)
            if score:
                candidates.append((score, "document", item))

        candidates.sort(key=lambda entry: entry[0], reverse=True)
        context = []
        seen = set()
        for _, kind, item in candidates:
            title = str(item.get("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            summary = self._sentence(item.get("summary") or title)
            if kind == "situation":
                sources = int(item.get("source_count") or 0)
                confidence = round(float(item.get("confidence") or 0) * 100)
                context.append(
                    f"{title}: {summary} Evidence support {confidence}% "
                    f"across {sources} publisher(s)."
                )
            else:
                context.append(f"Recent evidence: {title}. {summary}")
            if len(context) >= limit:
                break
        return context

    def _context_terms(self, value):
        stopwords = {
            "about", "after", "again", "against", "are", "been", "can",
            "could", "did", "does", "doing", "from", "had", "has", "have",
            "how", "into", "learned", "might", "right", "should", "that",
            "their", "there", "they", "think", "this", "through", "was",
            "were", "what", "when", "where", "which", "who", "why", "will",
            "with", "would", "world", "you", "your"
        }
        return {
            token for token in re.findall(r"[a-z0-9]+", str(value).lower())
            if len(token) >= 3 and token not in stopwords
        }

    def _overlap_score(self, item, terms):
        text = " ".join((
            str(item.get("title") or ""),
            str(item.get("summary") or "")
        )).lower()
        matches = sum(term in text for term in terms)
        if not matches:
            return 0
        return matches / max(1, len(terms))

    def _memories(self, topic):
        items = (
            self.memory_store.search(topic, limit=3)
            if topic else self.memory_store.list_memories(limit=5)
        )
        return [
            item for item in items
            if item.get("kind") not in {"conversation", "event"}
        ][:3]

    def _public_learning(self, topic):
        if self.intelligence_store is None:
            return []
        situations = self.intelligence_store.list_situations(limit=100)
        if topic:
            terms = self._terms(topic)
            situations = [
                item for item in situations
                if self._matches(item.get("title", ""), terms)
                or self._matches(item.get("summary", ""), terms)
            ]
        else:
            corroborated = [
                item for item in situations
                if int(item.get("source_count") or 0) >= 2
                or item.get("status") == "contested"
            ]
            situations = corroborated or situations

        lines = []
        for item in situations[:3]:
            confidence = round(float(item.get("confidence") or 0) * 100)
            sources = int(item.get("source_count") or 0)
            lines.append(
                f"{item.get('title', 'Situation')} "
                f"({confidence}% support across {sources} publisher"
                f"{'s' if sources != 1 else ''}). "
                f"World-model conclusion: "
                f"{item.get('worldview') or 'No synthesis yet.'}"
            )
        if lines:
            return ["Public world model: " + " ".join(lines)]

        if topic:
            documents = self.intelligence_store.list_documents(limit=200)
            terms = self._terms(topic)
            matches = [
                item for item in documents
                if item.get("category") != "prediction-market"
                and (
                    self._matches(item.get("title", ""), terms)
                    or self._matches(item.get("summary", ""), terms)
                )
            ][:3]
            if matches:
                return [
                    "Recent public evidence, not yet a corroborated conclusion: "
                    + " ".join(self._sentence(item["title"]) for item in matches)
                ]
        return []

    def _terms(self, value):
        return {
            token for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) >= 3
        }

    def _matches(self, value, terms):
        text = str(value or "").lower()
        return bool(terms) and all(term in text for term in terms)

    def _sentence(self, value):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = text[:280].rstrip(" ,;:")
        return text if text.endswith((".", "!", "?")) else text + "."


class WorldviewDigest:
    """Speak the stored public-world model without exposing model reasoning."""

    def __init__(self, intelligence_store=None):
        self.intelligence_store = intelligence_store

    def build(self, limit=3):
        if self.intelligence_store is None:
            return (
                "I do not have a connected intelligence store, so I cannot "
                "give an evidence-grounded reading of the world yet."
            )

        try:
            situations = self.intelligence_store.list_situations(limit=100)
        except Exception:
            return (
                "I could not read the world model just now, so I do not want "
                "to improvise a view of current events."
            )

        candidates = [
            item for item in situations
            if str(item.get("worldview") or "").strip()
        ]
        if not candidates:
            return (
                "I have collected public intelligence, but I do not have any "
                "synthesized world conclusions to report yet."
            )

        candidates.sort(key=self._priority, reverse=True)
        if all(int(item.get("source_count") or 0) < 2 for item in candidates):
            lines = [
                "My current reading is that the feeds are concentrated in "
                "official, local alerts. I do not yet have enough independent "
                "cross-source reporting to make a broad global conclusion."
            ]
        else:
            lines = [
                "My current reading is based on the stored evidence across the "
                "intelligence feeds, not private model reasoning."
            ]
        for situation in candidates[:max(1, min(5, int(limit)))]:
            lines.append(self._describe(situation))
        lines.append(
            "These are evidence-weighted conclusions, not certainties."
        )
        return " ".join(lines)

    def _priority(self, item):
        sources = int(item.get("source_count") or 0)
        confidence = float(item.get("worldview_confidence") or item.get("confidence") or 0)
        contested = str(item.get("status") or "").lower() == "contested"
        # The store already sorts by recency after confidence; this makes
        # corroboration and disagreement prominent in a spoken overview.
        return (contested, sources >= 2, confidence, str(item.get("updated_at") or ""))

    def _describe(self, situation):
        title = self._sentence(
            str(situation.get("title") or "A current situation")[:180]
        )
        conclusion = self._sentence(situation.get("worldview"))
        sources = int(situation.get("source_count") or 0)
        confidence = round(float(
            situation.get("worldview_confidence") or situation.get("confidence") or 0
        ) * 100)
        source_label = "publisher" if sources == 1 else "publishers"
        line = (
            f"{title} {conclusion} This assessment has {confidence}% support "
            f"across {sources} {source_label}."
        )
        if sources < 2:
            line += " It is provisional because it has not been independently corroborated."

        synthesis = self._latest_synthesis(situation.get("id"))
        contradictions = synthesis.get("contradictions", []) if synthesis else []
        questions = synthesis.get("open_questions", []) if synthesis else []
        if str(situation.get("status") or "").lower() == "contested":
            detail = self._first(contradictions) or "the available sources disagree"
            line += f" Important disagreement: {self._sentence(detail)}"
        elif questions:
            line += f" Key open question: {self._sentence(self._first(questions))}"
        return line

    def _latest_synthesis(self, situation_id):
        if not situation_id or not hasattr(self.intelligence_store, "worldview_syntheses"):
            return {}
        try:
            rows = self.intelligence_store.worldview_syntheses(situation_id, limit=1)
        except Exception:
            return {}
        return rows[0] if rows else {}

    def _first(self, values):
        if isinstance(values, list) and values:
            return str(values[0])
        return ""

    def _sentence(self, value):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = text[:360].rstrip(" ,;:")
        return text if text.endswith((".", "!", "?")) else text + "."
