import hashlib
import json
import re
from dataclasses import dataclass


FEATURE_VERSION = "event-features-v2"
FEATURE_STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "is",
    "of", "on", "or", "the", "to", "update", "updates", "with", "new",
    "live", "breaking", "report", "reports", "reported", "says", "said"
}
GENERIC_ENTITY_KEYS = {
    "breaking", "category", "depth", "earthquake", "green", "magnitude",
    "media", "media-post", "notification", "population", "special-weather",
    "special-weather-statement", "statement", "storm", "tropical-cyclone",
    "weather", "world"
}
ENTITY_METADATA_KEYS = (
    "place", "places", "country", "countries", "region", "regions",
    "city", "cities", "organization", "organizations", "actor", "actors",
    "disasters", "event", "office"
)


@dataclass(frozen=True)
class DocumentFeatures:
    normalized_title: str
    occurred_at: str
    entity_keys: tuple[str, ...]
    location_key: str
    lexical_signature: tuple[str, ...]
    content_fingerprint: str
    latitude: float | None = None
    longitude: float | None = None

    def as_record(self):
        return {
            "feature_version": FEATURE_VERSION,
            "normalized_title": self.normalized_title,
            "occurred_at": self.occurred_at,
            "entity_keys": json.dumps(self.entity_keys),
            "location_key": self.location_key,
            "lexical_signature": json.dumps(self.lexical_signature),
            "content_fingerprint": self.content_fingerprint,
        }


def extract_document_features(document):
    title = str(document.get("title") or "")
    summary = str(document.get("summary") or "")
    metadata = document.get("metadata") or {}
    normalized_title = _normalize_text(title)
    signature = tuple(sorted(_tokens(f"{title} {summary}")))[:80]
    entities = set(_metadata_entities(metadata))
    entities.update(_named_phrases(title))
    latitude = _float_or_none(document.get("latitude"))
    longitude = _float_or_none(document.get("longitude"))
    location_key = ""
    if latitude is not None and longitude is not None:
        location_key = f"{round(latitude, 1):.1f},{round(longitude, 1):.1f}"
    fingerprint_text = " ".join(
        re.findall(r"[a-z0-9]+", f"{title} {summary}".lower())
    )
    fingerprint_tokens = fingerprint_text.split()
    generic_title = bool(re.match(
        r"^(media post from|update from|breaking)", title.strip(), re.I
    ))
    fingerprint = ""
    if len(fingerprint_tokens) >= 6 and not (generic_title and not summary.strip()):
        fingerprint = hashlib.sha256(
            fingerprint_text.encode("utf-8")
        ).hexdigest()
    return DocumentFeatures(
        normalized_title=normalized_title,
        occurred_at=str(
            document.get("published_at") or document.get("retrieved_at") or ""
        ),
        entity_keys=tuple(sorted(entities))[:40],
        location_key=location_key,
        lexical_signature=signature,
        content_fingerprint=fingerprint,
        latitude=latitude,
        longitude=longitude
    )


def token_similarity(left, right):
    left = set(left or ())
    right = set(right or ())
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def entity_similarity(left, right):
    left = set(left or ())
    right = set(right or ())
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, min(len(left), len(right)))


def _tokens(value):
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(token) > 2 and token not in FEATURE_STOP_WORDS
    }


def _normalize_text(value):
    return " ".join(sorted(_tokens(value)))


def _metadata_entities(metadata):
    for key in ENTITY_METADATA_KEYS:
        value = metadata.get(key)
        values = value if isinstance(value, (list, tuple, set)) else [value]
        for item in values:
            normalized = _entity_key(item)
            if normalized:
                yield normalized


def _named_phrases(title):
    phrases = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9.'-]+(?:\s+|$)){1,4}", str(title or "")
    )
    for phrase in phrases:
        normalized = _entity_key(phrase)
        parts = set(normalized.split("-"))
        if (
            normalized
            and normalized not in FEATURE_STOP_WORDS
            and normalized not in GENERIC_ENTITY_KEYS
            and not parts.issubset(GENERIC_ENTITY_KEYS | FEATURE_STOP_WORDS)
        ):
            yield normalized


def _entity_key(value):
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return normalized if len(normalized) > 2 else ""


def _float_or_none(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
