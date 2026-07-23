import json
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class XConnector(JsonConnector):
    source_id = "x_public"
    name = "X public signals (read-only)"
    kind = "social_signal"
    base_url = "https://api.x.com/2"
    credibility = 0.35
    poll_seconds = 900

    def __init__(
        self,
        bearer_token="",
        usernames=(),
        search_queries=(),
        poll_seconds=900,
        fetch_api=None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.bearer_token = str(bearer_token or "").strip()
        self.usernames = tuple(_valid_username(value) for value in usernames)
        self.usernames = tuple(value for value in self.usernames if value)
        self.search_queries = tuple(
            str(value).strip()[:450] for value in search_queries
            if str(value).strip()
        )
        self.poll_seconds = max(300, int(poll_seconds))
        self._fetch_api_override = fetch_api
        self.enabled = (
            self.enabled
            and bool(self.bearer_token)
            and bool(self.usernames or self.search_queries)
        )

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})
        cursor = dict(cursor or {})
        collected = {}
        next_cursor = {
            "search_since_ids": dict(cursor.get("search_since_ids") or {})
        }
        queries = self._combined_queries()
        request_count = min(len(queries), max(1, self.max_items // 10))
        start_index = int(cursor.get("next_query_index") or 0) % len(queries)
        selected = [queries[(start_index + offset) % len(queries)] for offset in range(request_count)]
        per_request = min(100, max(10, self.max_items // request_count))

        for query in selected:
            key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
            params = self._post_params(per_request)
            params["query"] = query
            since_id = next_cursor["search_since_ids"].get(key)
            if since_id:
                params["since_id"] = since_id
            response = self._request("/tweets/search/recent", params)
            self._collect(response, collected, f"recent-search:{query}")
            newest = _newest_id(response.get("data") or [])
            if newest:
                next_cursor["search_since_ids"][key] = newest

        items = [
            _source_item(record["post"], record["author"], record["contexts"])
            for record in collected.values()
        ][:self.max_items]
        next_cursor["retrieved_at"] = utc_now()
        next_cursor["next_query_index"] = (
            start_index + request_count
        ) % len(queries)
        return ConnectorBatch(items=items, cursor=next_cursor)

    def _combined_queries(self):
        parts = [f"from:{username}" for username in self.usernames]
        parts.extend(f"({query})" for query in self.search_queries)
        chunks = []
        current = []
        for part in parts:
            candidate = "(" + " OR ".join(current + [part]) + ") -is:retweet"
            if current and len(candidate) > 512:
                chunks.append("(" + " OR ".join(current) + ") -is:retweet")
                current = [part]
            else:
                current.append(part)
        if current:
            chunks.append("(" + " OR ".join(current) + ") -is:retweet")
        return chunks

    def _post_params(self, max_results):
        return {
            "max_results": max_results,
            "expansions": "author_id",
            "tweet.fields": (
                "id,text,author_id,created_at,conversation_id,lang,"
                "public_metrics,referenced_tweets,possibly_sensitive"
            ),
            "user.fields": "id,name,username,verified,verified_type,public_metrics"
        }

    def _collect(self, response, collected, context):
        authors = {
            str(user.get("id")): user
            for user in (response.get("includes") or {}).get("users", [])
        }
        for post in response.get("data") or []:
            post_id = str(post.get("id") or "")
            if not post_id:
                continue
            record = collected.setdefault(
                post_id,
                {
                    "post": post,
                    "author": authors.get(str(post.get("author_id")), {}),
                    "contexts": set()
                }
            )
            record["contexts"].add(context)

    def _request(self, path, params):
        url = self.base_url + path + "?" + urllib.parse.urlencode(params)
        if self._fetch_api_override:
            return self._fetch_api_override(url)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.bearer_token}",
                "User-Agent": "EntityIntelligence/0.3"
            }
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                reset = exc.headers.get("x-rate-limit-reset")
                wait = max(0, int(reset) - int(time.time())) if reset else None
                detail = f" Retry after approximately {wait} seconds." if wait is not None else ""
                raise RuntimeError("X API rate limit reached." + detail) from exc
            if exc.code in {401, 403}:
                raise RuntimeError(
                    "X API authorization or account credits do not permit this read."
                ) from exc
            raise RuntimeError(f"X API request failed with HTTP {exc.code}.") from exc


def _source_item(post, author, contexts):
    post_id = str(post["id"])
    username = str(author.get("username") or post.get("author_id") or "unknown")
    text = re.sub(r"\s+", " ", str(post.get("text") or "")).strip()
    references = post.get("referenced_tweets") or []
    return SourceItem(
        external_id=post_id,
        title=text[:280] or f"Post from @{username}",
        url=f"https://x.com/{urllib.parse.quote(username)}/status/{post_id}",
        summary=text[:2000],
        content=text[:20_000],
        published_at=post.get("created_at"),
        category=_signal_category(text),
        metadata={
            "visibility": "public",
            "platform": "x",
            "author_id": post.get("author_id"),
            "author_username": username,
            "author_name": author.get("name"),
            "author_verified": bool(author.get("verified")),
            "author_verified_type": author.get("verified_type"),
            "author_public_metrics": author.get("public_metrics") or {},
            "post_public_metrics": post.get("public_metrics") or {},
            "conversation_id": post.get("conversation_id"),
            "language": post.get("lang"),
            "possibly_sensitive": bool(post.get("possibly_sensitive")),
            "references": references,
            "collection_contexts": sorted(contexts)
        }
    )


def _valid_username(value):
    username = str(value or "").strip().lstrip("@")
    if re.fullmatch(r"[A-Za-z0-9_]{1,15}", username):
        return username
    return ""


def _newest_id(posts):
    ids = [str(post.get("id")) for post in posts if str(post.get("id") or "").isdigit()]
    return max(ids, key=int) if ids else None


def _signal_category(text):
    normalized = str(text or "").lower()
    categories = (
        ("earthquake", ("earthquake", "aftershock", "seismic")),
        ("wildfires", ("wildfire", "bushfire", "forest fire")),
        ("severe-storms", ("hurricane", "typhoon", "cyclone", "tornado")),
        ("floods", ("flood", "flash flooding")),
        ("humanitarian", ("humanitarian", "refugee", "displacement", "aid convoy"))
    )
    for category, keywords in categories:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "social-signal"
