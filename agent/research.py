import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser

from agent.models.base import ModelUnavailable
from agent.models.router import ModelRouter


@dataclass
class ResearchSource:
    title: str
    url: str
    snippet: str = ""


@dataclass
class ResearchResult:
    query: str
    summary: str
    sources: list[ResearchSource] = field(default_factory=list)
    confidence: float = 0.0

    def format_response(self):
        if not self.sources:
            return f"I could not find reliable research results for: {self.query}."

        lines = [
            self.summary or f"Research results for: {self.query}."
        ]

        for index, source in enumerate(self.sources, start=1):
            lines.append(f"{index}. {source.title}: {source.url}")

        return " ".join(lines)


class ResearchTool:
    def __init__(self, router=None):
        self.enabled = self._env_bool("ENTITY_RESEARCH_ENABLED")
        self.max_results = self._env_int(
            "ENTITY_RESEARCH_MAX_RESULTS",
            default=3,
            minimum=1
        )
        self.timeout = self._env_int(
            "ENTITY_RESEARCH_TIMEOUT_SECONDS",
            default=10,
            minimum=1
        )
        self.store_by_default = self._env_bool(
            "ENTITY_RESEARCH_STORE_BY_DEFAULT"
        )
        self.router = router or ModelRouter()

    def setup_status(self):
        if not self.enabled:
            return "Internet research disabled."

        return f"Internet research enabled. Max results: {self.max_results}."

    def search(self, query):
        if not self.enabled:
            return ResearchResult(
                query=query,
                summary=(
                    "Internet research is disabled. Set "
                    "ENTITY_RESEARCH_ENABLED=true to use it."
                )
            )

        query = query.strip()

        if not query:
            return ResearchResult(
                query=query,
                summary="No research query provided."
            )

        try:
            sources = self._duckduckgo_search(query)
        except RuntimeError:
            sources = []

        if not sources:
            sources = self._wikipedia_search(query)

        summary = self._summarize(query, sources)

        return ResearchResult(
            query=query,
            summary=summary,
            sources=sources,
            confidence=0.6 if sources else 0.0
        )

    def _duckduckgo_search(self, query):
        params = urllib.parse.urlencode(
            {
                "q": query
            }
        )
        request = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?{params}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 EntityResearch/1.0 "
                    "(local personal assistant)"
                )
            }
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise RuntimeError(f"Research search failed: {exc}") from exc

        parser = DuckDuckGoParser(max_results=self.max_results)
        parser.feed(body)
        return parser.sources

    def _wikipedia_search(self, query):
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "srlimit": self.max_results
            }
        )
        request = urllib.request.Request(
            f"https://en.wikipedia.org/w/api.php?{params}",
            headers={
                "User-Agent": (
                    "EntityResearch/1.0 "
                    "(local personal assistant; contact: local)"
                )
            }
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout
            ) as response:
                payload = response.read().decode("utf-8", errors="replace")
        except Exception:
            return []

        try:
            data = json.loads(payload)
        except ValueError:
            return []

        sources = []

        for item in data.get("query", {}).get("search", []):
            title = item.get("title", "")
            page_id = item.get("pageid")
            snippet = re.sub("<[^>]+>", "", item.get("snippet", ""))

            if not title or not page_id:
                continue

            sources.append(
                ResearchSource(
                    title=title,
                    url=f"https://en.wikipedia.org/?curid={page_id}",
                    snippet=self._clean_snippet(snippet)
                )
            )

            if len(sources) >= self.max_results:
                break

        return sources

    def _summarize(self, query, sources):
        if not sources:
            return f"I could not find search results for: {query}."

        fallback = self._fallback_summary(query, sources)

        try:
            summary = self.router.generate(
                self._summary_prompt(query, sources),
                user_input=query,
                routing="research"
            )
        except ModelUnavailable:
            return fallback
        except Exception:
            return fallback

        summary = re.sub(r"\s+", " ", summary).strip()

        return summary or fallback

    def _summary_prompt(self, query, sources):
        source_text = "\n".join(
            f"- {source.title}: {source.snippet} ({source.url})"
            for source in sources
        )

        return (
            "Summarize these web search results for Entity. Be concise, "
            "avoid claiming certainty beyond the snippets, and mention when "
            "the result should be verified from the source. Do not invent "
            "facts not present in the snippets.\n\n"
            f"Query: {query}\n"
            f"Sources:\n{source_text}"
        )

    def _fallback_summary(self, query, sources):
        snippets = [
            source.snippet
            for source in sources
            if source.snippet
        ]

        if snippets:
            return (
                f"Research results for {query}: "
                + " ".join(snippets[:2])
            )

        return f"Research found {len(sources)} result(s) for {query}."

    def _clean_snippet(self, snippet):
        snippet = html.unescape(snippet)
        return re.sub(r"\s+", " ", snippet).strip()

    def _env_bool(self, name):
        return os.getenv(name, "").lower().strip() in {
            "1",
            "true",
            "yes",
            "on"
        }

    def _env_int(self, name, default, minimum):
        try:
            value = int(os.getenv(name, str(default)))
        except ValueError:
            value = default

        return max(minimum, value)


class DuckDuckGoParser(HTMLParser):
    def __init__(self, max_results=3):
        super().__init__()
        self.max_results = max_results
        self.sources = []
        self._in_result_link = False
        self._in_snippet = False
        self._current_link = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")

        if tag == "a" and "result__a" in classes:
            self._in_result_link = True
            self._current_link = self._clean_url(attrs.get("href", ""))
            self._text = []

        if tag in {"a", "div"} and "result__snippet" in classes:
            self._in_snippet = True
            self._text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_result_link:
            title = self._clean_text("".join(self._text))

            if title and self._current_link and len(self.sources) < self.max_results:
                self.sources.append(
                    ResearchSource(
                        title=title,
                        url=self._current_link
                    )
                )

            self._in_result_link = False
            self._current_link = None
            self._text = []

        if self._in_snippet and tag in {"a", "div"}:
            snippet = self._clean_text("".join(self._text))

            if snippet and self.sources:
                last = self.sources[-1]

                if not last.snippet:
                    last.snippet = snippet

            self._in_snippet = False
            self._text = []

    def handle_data(self, data):
        if self._in_result_link or self._in_snippet:
            self._text.append(data)

    def _clean_text(self, text):
        text = html.unescape(text)
        return re.sub(r"\s+", " ", text).strip()

    def _clean_url(self, url):
        url = html.unescape(url)

        if url.startswith("//duckduckgo.com/l/?"):
            parsed = urllib.parse.urlparse("https:" + url)
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("uddg", [""])[0]
            return urllib.parse.unquote(target)

        return url
