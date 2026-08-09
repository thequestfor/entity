"""Conservative document-level place inference with explicit provenance."""

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

from agent.intelligence.geospatial import COUNTRY_CODES, _distance_km
from agent.intelligence.store import utc_now


METHOD = "grounded-place-inference-v1"
COUNTRY_NAME_TO_CODE = {}
for _code, _name in COUNTRY_CODES.items():
    if len(_code) == 2 or _name.lower() not in COUNTRY_NAME_TO_CODE:
        COUNTRY_NAME_TO_CODE[_name.lower()] = _code if len(_code) == 2 else ""
COMMON_AMBIGUOUS_PLACES = {
    "alert", "central", "reading", "mobile", "normal", "union", "victory",
    "advance", "airport", "international", "national", "new town",
}


@dataclass(frozen=True)
class LocationCandidate:
    label: str = ""
    country_code: str = ""
    country_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    precision_km: float | None = None
    confidence: float = 0.0
    evidence: str = ""
    source: str = ""


class DocumentLocationInferenceEngine:
    """Infer where an event occurred without silently inventing coordinates."""

    def __init__(
        self, store, router=None, enabled=True, model_enabled=True,
        geocoding_enabled=True, batch_size=25, model_calls_per_cycle=5,
        timeout=10,
        geocode_url="https://geocoding-api.open-meteo.com/v1/search",
        fetch_json=None,
    ):
        self.store = store
        self.router = router
        self.enabled = bool(enabled)
        self.model_enabled = bool(model_enabled and router is not None)
        self.geocoding_enabled = bool(geocoding_enabled)
        self.batch_size = max(1, min(200, int(batch_size)))
        self.model_calls_per_cycle = max(0, min(25, int(model_calls_per_cycle)))
        self.timeout = max(1, int(timeout))
        self.geocode_url = str(geocode_url).rstrip("?")
        self.fetch_json = fetch_json or self._fetch_json

    def run_batch(self):
        if not self.enabled:
            return {"processed": 0, "located": 0, "country_only": 0}
        with self.store._connect() as connection:
            rows = connection.execute(
                """
                SELECT documents.*, versions.id AS document_version_id,
                       versions.metadata AS version_metadata
                FROM documents
                JOIN sources ON sources.id=documents.source_id
                JOIN document_versions versions ON versions.document_id=documents.id
                 AND versions.version=(SELECT MAX(latest.version)
                    FROM document_versions latest
                    WHERE latest.document_id=documents.id)
                LEFT JOIN document_location_inferences inference
                  ON inference.document_version_id=versions.id
                 AND inference.method=?
                WHERE (inference.id IS NULL OR (
                       inference.status='no-grounded-location'
                       AND julianday(inference.updated_at)<julianday('now','-6 hours')
                      ))
                  AND documents.status='active'
                  AND documents.latitude IS NULL AND documents.longitude IS NULL
                  AND sources.kind NOT IN (
                    'private_mail','prediction_market','weather_forecast',
                    'infrastructure_reference'
                  )
                ORDER BY COALESCE(documents.published_at,
                                  documents.retrieved_at) DESC
                LIMIT ?
                """, (METHOD, self.batch_size)
            ).fetchall()
            documents = [dict(row) for row in rows]

        processed = located = country_only = model_calls = 0
        references = self._reference_entries()
        for document in documents:
            metadata = self.store._json_load(document.get("metadata"), {})
            document["metadata"] = metadata
            candidate = self._structured_candidate(document)
            if not candidate:
                candidate = self._reference_candidate(document, references)
            model_attempted = False
            if (
                not candidate and self.model_enabled
                and model_calls < self.model_calls_per_cycle
            ):
                model_calls += 1
                model_attempted = True
                candidate = self._model_candidate(document)
            if not candidate and self.model_enabled and not model_attempted:
                # Leave it pending for a later bounded model slot.
                continue
            if (
                candidate and candidate.latitude is None and candidate.label
                and candidate.source != "country-name-match"
            ):
                candidate = self._resolve_candidate(candidate)
            self._record(document, candidate)
            processed += 1
            if candidate and candidate.latitude is not None:
                located += 1
            elif candidate and candidate.country_name:
                country_only += 1
        return {
            "processed": processed, "located": located,
            "country_only": country_only, "model_calls": model_calls,
        }

    def _structured_candidate(self, document):
        metadata = document.get("metadata") or {}
        label = next((str(metadata.get(key) or "").strip() for key in (
            "locality", "place", "location_name", "city"
        ) if str(metadata.get(key) or "").strip()), "")
        country = metadata.get("country") or metadata.get("country_name") or ""
        if isinstance(country, (list, tuple)):
            country = country[0] if len(country) == 1 else ""
        country = str(country or "").strip()
        code = str(metadata.get("country_code") or "").strip().upper()[:2]
        if code and not country:
            country = COUNTRY_CODES.get(code, "")
        if not label and not country:
            return None
        return LocationCandidate(
            label=label or country, country_code=code,
            country_name=country, confidence=.9,
            evidence=label or country, source="structured-source-metadata",
        )

    def _reference_entries(self):
        entries = []
        with self.store._connect() as connection:
            rows = connection.execute(
                """
                SELECT title,latitude,longitude,metadata
                FROM documents
                WHERE source_id IN ('ourairports','nga_world_port_index')
                  AND latitude IS NOT NULL AND longitude IS NOT NULL
                """
            ).fetchall()
        for row in rows:
            metadata = self.store._json_load(row["metadata"], {})
            aliases = {
                str(row["title"] or "").strip(),
                str(metadata.get("name") or "").strip(),
                str(metadata.get("municipality") or "").strip(),
            }
            entries.append((row, metadata, aliases))
        return entries

    def _reference_candidate(self, document, entries=None):
        text = _document_text(document)
        normalized = _normalize(text)
        if not normalized:
            return None
        matches = []
        for row, metadata, aliases in entries or self._reference_entries():
            country_code = str(metadata.get("country_code") or "").upper()[:2]
            country_name = COUNTRY_CODES.get(country_code, "")
            for alias in aliases:
                clean = _normalize(alias)
                if (
                    len(clean) < 5 or clean in COMMON_AMBIGUOUS_PLACES
                    or not _grounded_place_mention(normalized, clean)
                ):
                    continue
                matches.append(LocationCandidate(
                    label=alias, country_code=country_code,
                    country_name=country_name, latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]), precision_km=35.0,
                    confidence=.78, evidence=_evidence(text, alias),
                    source="local-reference-gazetteer",
                ))
        matches = _collapse_nearby(matches)
        if len(matches) == 1:
            return matches[0]

        country_matches = []
        for name, code in COUNTRY_NAME_TO_CODE.items():
            if len(name) >= 4 and _locative_mention(normalized, name):
                country_matches.append((name, code))
        unique_countries = {name for name, _ in country_matches}
        if len(unique_countries) == 1:
            name, code = country_matches[0]
            return LocationCandidate(
                label=name.title(), country_code=code,
                country_name=name.title(), confidence=.62,
                evidence=_evidence(text, name), source="country-name-match",
            )
        return None

    def _model_candidate(self, document):
        text = _document_text(document)[:5000]
        try:
            payload = self.router.generate_json(
                _location_prompt(text), user_input=str(document.get("title") or "")[:500],
                routing="world_understanding",
            )
        except Exception as exc:
            print(f"Location inference model unavailable: {type(exc).__name__}")
            return None
        if not isinstance(payload, dict) or not payload.get("location"):
            return None
        evidence = str(payload.get("evidence") or "").strip()
        if not evidence or evidence.lower() not in text.lower():
            return None
        try:
            confidence = float(payload.get("confidence") or 0)
        except (TypeError, ValueError):
            return None
        if confidence < .55:
            return None
        country = str(payload.get("country") or "").strip()
        return LocationCandidate(
            label=str(payload["location"]).strip()[:160],
            country_code=COUNTRY_NAME_TO_CODE.get(country.lower(), ""),
            country_name=country[:120], confidence=min(.9, confidence),
            evidence=evidence[:500], source="model-grounded-place-extraction",
        )

    def _resolve_candidate(self, candidate):
        if not self.geocoding_enabled:
            return candidate
        query = candidate.label
        if candidate.country_name and candidate.country_name.lower() not in query.lower():
            query += f", {candidate.country_name}"
        try:
            params = urllib.parse.urlencode({
                "name": query, "count": 5, "language": "en", "format": "json"
            })
            payload = self.fetch_json(f"{self.geocode_url}?{params}")
        except Exception as exc:
            print(f"Location geocoder unavailable: {type(exc).__name__}")
            return candidate
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            return candidate
        requested_country = candidate.country_name.lower()
        if candidate.country_code:
            results = [
                item for item in results
                if str(item.get("country_code") or "").upper()
                == candidate.country_code
            ]
        elif requested_country:
            matching = [
                item for item in results
                if str(item.get("country") or "").lower() == requested_country
            ]
            if matching:
                results = matching
        for item in results:
            try:
                latitude, longitude = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            country_name = str(item.get("country") or candidate.country_name)
            country_code = str(item.get("country_code") or candidate.country_code).upper()[:2]
            label = str(item.get("name") or candidate.label)
            if not _compatible_place_name(candidate.label, label):
                continue
            admin = str(item.get("admin1") or "")
            if admin and admin.lower() not in label.lower():
                label = f"{label}, {admin}"
            return LocationCandidate(
                label=label[:160], country_code=country_code,
                country_name=country_name[:120], latitude=latitude,
                longitude=longitude, precision_km=25.0,
                confidence=round(min(.9, candidate.confidence * .9), 4),
                evidence=candidate.evidence, source=candidate.source + "+open-meteo",
            )
        return candidate

    def _record(self, document, candidate):
        now = utc_now()
        status = "located" if candidate and candidate.latitude is not None else (
            "country-only" if candidate and candidate.country_name else "no-grounded-location"
        )
        candidate = candidate or LocationCandidate()
        with self.store._connect() as connection:
            connection.execute(
                """
                INSERT INTO document_location_inferences (
                  document_id,document_version_id,location_label,country_code,
                  country_name,latitude,longitude,precision_km,confidence,
                  evidence_excerpt,candidate_source,status,method,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(document_version_id,method) DO UPDATE SET
                  location_label=excluded.location_label,
                  country_code=excluded.country_code,
                  country_name=excluded.country_name,
                  latitude=excluded.latitude,longitude=excluded.longitude,
                  precision_km=excluded.precision_km,
                  confidence=excluded.confidence,
                  evidence_excerpt=excluded.evidence_excerpt,
                  candidate_source=excluded.candidate_source,
                  status=excluded.status,updated_at=excluded.updated_at
                """, (
                    document["id"], document["document_version_id"], candidate.label,
                    candidate.country_code, candidate.country_name,
                    candidate.latitude, candidate.longitude, candidate.precision_km,
                    candidate.confidence, candidate.evidence, candidate.source,
                    status, METHOD, now, now,
                )
            )
            if status == "no-grounded-location":
                return
            metadata = dict(document.get("metadata") or {})
            if candidate.country_name:
                metadata["country"] = candidate.country_name
            if candidate.country_code:
                metadata["country_code"] = candidate.country_code
            if candidate.label:
                metadata["location_name"] = candidate.label
            metadata["location_inference"] = {
                "confidence": candidate.confidence,
                "precision_km": candidate.precision_km,
                "evidence": candidate.evidence,
                "method": METHOD,
                "source": candidate.source,
            }
            connection.execute(
                """UPDATE documents SET latitude=COALESCE(latitude,?),
                   longitude=COALESCE(longitude,?),metadata=?,updated_at=? WHERE id=?""",
                (candidate.latitude, candidate.longitude,
                 self.store._json(metadata), now, document["id"])
            )
            connection.execute(
                """UPDATE situations SET updated_at=? WHERE id IN (
                   SELECT situation_id FROM situation_documents WHERE document_id=?
                   )""", (now, document["id"])
            )

    def _fetch_json(self, url):
        request = urllib.request.Request(url, headers={
            "User-Agent": "Entity situation monitor/1.0"
        })
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def _document_text(document):
    return "\n".join(str(document.get(key) or "") for key in (
        "title", "summary", "content"
    ))


def _normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _contains_phrase(text, phrase):
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text))


def _locative_mention(text, phrase):
    prefix = (
        r"(?:in|near|at|inside|outside|across|throughout|around|off|over|"
        r"east of|west of|north of|south of)"
    )
    return bool(re.search(
        rf"(?<![a-z0-9]){prefix}(?: [a-z0-9]+){{0,4}} "
        rf"{re.escape(phrase)}(?![a-z0-9])", text
    ))


def _grounded_place_mention(text, phrase):
    if not _contains_phrase(text, phrase):
        return False
    if _locative_mention(text, phrase):
        return True
    # A named facility is sufficiently specific even without a preposition.
    return bool(re.search(
        r"\b(?:airport|air base|port|harbour|harbor|terminal|naval base)$",
        phrase
    ))


def _evidence(text, phrase):
    match = re.search(re.escape(phrase), text, re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"\s+", " ", text[max(0, match.start()-100):match.end()+100]).strip()[:500]


def _compatible_place_name(candidate, result):
    candidate_name = _normalize(str(candidate).split(",", 1)[0])
    result_name = _normalize(result)
    if not candidate_name or not result_name:
        return False
    if candidate_name in result_name or result_name in candidate_name:
        return True
    left = {token for token in candidate_name.split() if len(token) >= 4}
    right = {token for token in result_name.split() if len(token) >= 4}
    return bool(left and len(left & right) / len(left) >= .5)


def _collapse_nearby(matches):
    unique = []
    for item in sorted(matches, key=lambda value: len(value.label), reverse=True):
        if any(_distance_km(
            (item.latitude, item.longitude), (other.latitude, other.longitude)
        ) <= 50 for other in unique):
            continue
        unique.append(item)
    return unique


def _location_prompt(text):
    return (
        "Extract the single best-supported location where the reported event happened. "
        "Do not use the publisher's home, an actor's nationality, a dateline, or a place "
        "mentioned only as background. If several event locations are equally plausible, "
        "return location as an empty string. Never invent coordinates. Return JSON only: "
        '{"location":"city/place, region","country":"country name",'
        '"confidence":0.0,"evidence":"exact quote from input"}. '
        "The evidence must occur verbatim in the input. Input:\n" + text
    )
