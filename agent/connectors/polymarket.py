import json
import urllib.parse

from agent.connectors.base import JsonConnector
from agent.intelligence.models import ConnectorBatch, SourceItem
from agent.intelligence.store import utc_now


class PolymarketConnector(JsonConnector):
    source_id = "polymarket"
    name = "Polymarket"
    kind = "prediction_market"
    base_url = "https://gamma-api.polymarket.com/markets"
    credibility = 0.25
    poll_seconds = 300

    def __init__(self, poll_seconds=300, **kwargs):
        super().__init__(**kwargs)
        self.poll_seconds = max(60, int(poll_seconds))

    def poll(self, cursor=None):
        if not self.enabled:
            return ConnectorBatch(cursor=cursor or {})

        request_limit = min(100, max(self.max_items, 20))
        query = urllib.parse.urlencode({
            "active": "true",
            "closed": "false",
            "limit": request_limit,
            "order": "volume24hr",
            "ascending": "false"
        })
        payload = self.fetch_json(f"{self.base_url}?{query}")
        markets = payload if isinstance(payload, list) else payload.get("markets", [])
        items = [self._normalize(market) for market in markets[:self.max_items]]
        items = [item for item in items if item.external_id and item.title]
        return ConnectorBatch(items=items, cursor={
            "retrieved_at": utc_now(),
            "market_ids": [item.external_id for item in items]
        })

    def _normalize(self, market):
        outcomes = _json_list(market.get("outcomes"))
        prices = _json_list(market.get("outcomePrices"))
        probabilities = []
        for index, outcome in enumerate(outcomes):
            try:
                probability = round(float(prices[index]) * 100, 1)
            except (IndexError, TypeError, ValueError):
                continue
            probabilities.append({
                "outcome": str(outcome),
                "probability_percent": probability
            })
        forecast = ", ".join(
            f"{entry['outcome']} {entry['probability_percent']:g}%"
            for entry in probabilities
        ) or "No current outcome prices"
        event = (market.get("events") or [{}])[0] or {}
        event_slug = str(event.get("slug") or "").strip()
        market_slug = str(market.get("slug") or "").strip()
        if event_slug and market_slug and event_slug != market_slug:
            url = f"https://polymarket.com/event/{event_slug}/{market_slug}"
        else:
            slug = event_slug or market_slug
            url = (
                f"https://polymarket.com/event/{slug}"
                if slug else "https://polymarket.com"
            )
        return SourceItem(
            external_id=str(market.get("id") or market.get("conditionId") or ""),
            title=str(market.get("question") or "Polymarket forecast").strip(),
            url=url,
            summary=(
                f"Market-implied probabilities: {forecast}. "
                "These prices reflect trader beliefs, not verified facts."
            ),
            published_at=market.get("createdAt"),
            category="prediction-market",
            metadata={
                "platform": "polymarket",
                "signal_type": "market_implied_probability",
                "factual_evidence": False,
                "condition_id": market.get("conditionId"),
                "event_title": event.get("title"),
                "outcomes": probabilities,
                "end_date": market.get("endDate"),
                "resolution_source": market.get("resolutionSource"),
                "volume": _number(market.get("volume")),
                "volume_24h": _number(market.get("volume24hr")),
                "liquidity": _number(market.get("liquidity"))
            }
        )


def _json_list(value):
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
