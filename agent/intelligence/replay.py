"""Offline, deterministic, network-free replay of bounded intelligence evidence."""

import argparse
import hashlib
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv

from agent.intelligence.claim_extraction import EXTRACTION_VERSION
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.event_assessment import (
    CanonicalEventAssessmentEngine, METHOD as ASSESSMENT_METHOD,
    POLICY_VERSION as EPISTEMIC_POLICY_VERSION,
)
from agent.intelligence.event_fusion import (
    EventFusionEngine, FEATURE_VERSION as FUSION_FEATURE_VERSION,
    METHOD as FUSION_METHOD,
)
from agent.intelligence.features import FEATURE_VERSION as DOCUMENT_FEATURE_VERSION
from agent.intelligence.framing import (
    COMPARISON_METHOD, METHOD as FRAMING_METHOD,
    EventFramingComparisonEngine, _validate as validate_framing,
)
from agent.intelligence.models import SourceItem
from agent.intelligence.replay_manifest import (
    build_manifest, canonical_json, fingerprint,
)
from agent.intelligence.source_registry import (
    POLICY_VERSION as SOURCE_POLICY_VERSION, SourcePolicy,
)
from agent.intelligence.store import IntelligenceStore, normalize_timestamp
from agent.intelligence.world_graph import (
    METHOD as WORLD_GRAPH_METHOD, WorldEventGraphEngine,
)


BUNDLE_VERSION = "replay-bundle-v1"
RUNNER_VERSION = "isolated-replay-v1"
DEFAULT_MAX_ITEMS = 2_000
DEFAULT_MAX_BYTES = 100_000_000
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_PASSES = 50
TOP_LEVEL_FIELDS = {
    "schema", "bundle_key", "cutoff", "sources", "documents", "captures",
    "frozen_responses", "expected_gaps", "declared_hash", "provenance",
}


class ReplayError(ValueError):
    def __init__(self, code, message=""):
        super().__init__(str(message or code)[:500])
        self.code = str(code)[:120]


class ReplayClock:
    def __init__(self, value):
        self._value = _timestamp(value)

    def advance(self, value):
        candidate = _timestamp(value)
        if candidate < self._value:
            raise ReplayError("clock-regression")
        self._value = candidate

    def iso(self):
        return self._value.isoformat(timespec="seconds").replace("+00:00", "Z")

    def __call__(self):
        return self.iso()


@dataclass(frozen=True)
class ReplayBundle:
    data: dict
    bundle_hash: str

    @classmethod
    def load(cls, path, max_items=DEFAULT_MAX_ITEMS,
             max_bytes=DEFAULT_MAX_BYTES):
        path = Path(path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise ReplayError("bundle-unreadable") from exc
        if size > max_bytes:
            raise ReplayError("bundle-too-large")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReplayError("bundle-invalid-json") from exc
        return cls.validate(data, max_items=max_items, max_bytes=max_bytes)

    @classmethod
    def validate(cls, data, max_items=DEFAULT_MAX_ITEMS,
                 max_bytes=DEFAULT_MAX_BYTES):
        if not isinstance(data, dict) or data.get("schema") != BUNDLE_VERSION:
            raise ReplayError("bundle-schema-mismatch")
        unknown = set(data) - TOP_LEVEL_FIELDS
        if unknown:
            raise ReplayError("bundle-unknown-field", sorted(unknown)[0])
        if not str(data.get("bundle_key") or "").strip():
            raise ReplayError("bundle-key-missing")
        cutoff = normalize_timestamp(data.get("cutoff"))
        if not cutoff:
            raise ReplayError("bundle-cutoff-invalid")
        sources = data.get("sources")
        documents = data.get("documents")
        captures = data.get("captures", [])
        responses = data.get("frozen_responses", [])
        gaps = data.get("expected_gaps", [])
        if not isinstance(sources, list) or not isinstance(documents, list):
            raise ReplayError("bundle-collections-invalid")
        if not all(isinstance(value, list) for value in (captures, responses, gaps)):
            raise ReplayError("bundle-collections-invalid")
        if len(documents) + len(captures) > max_items:
            raise ReplayError("bundle-item-limit")
        source_ids = {str(item.get("id") or "") for item in sources
                      if isinstance(item, dict)}
        if "" in source_ids or len(source_ids) != len(sources):
            raise ReplayError("bundle-source-invalid")
        for source in sources:
            policy = source.get("policy")
            if not isinstance(policy, dict):
                raise ReplayError("policy-snapshot-missing")
            if policy.get("policy_version") != SOURCE_POLICY_VERSION:
                raise ReplayError("policy-version-mismatch")
        for document in documents:
            if not isinstance(document, dict) or document.get("source_id") not in source_ids:
                raise ReplayError("document-source-invalid")
            _timestamp(document.get("captured_at"))
        for capture in captures:
            if not isinstance(capture, dict) or capture.get("source_id") not in source_ids:
                raise ReplayError("capture-source-invalid")
            _timestamp(capture.get("captured_at"))
            text = str(capture.get("normalized_text") or "")
            if len(text.encode("utf-8")) > min(max_bytes, 5_000_000):
                raise ReplayError("capture-too-large")
            actual = hashlib.sha256(text.encode()).hexdigest()
            if capture.get("content_hash") and capture["content_hash"] != actual:
                raise ReplayError("capture-hash-mismatch")
            capture["content_hash"] = actual
        capture_hashes = {item["content_hash"] for item in captures}
        response_hashes = set()
        for response in responses:
            if not isinstance(response, dict):
                raise ReplayError("frozen-response-invalid")
            if (response.get("method") != FRAMING_METHOD
                    or response.get("version") != FRAMING_METHOD):
                raise ReplayError("algorithm-version-mismatch")
            content_hash = str(response.get("content_hash") or "")
            if content_hash not in capture_hashes or content_hash in response_hashes:
                raise ReplayError("frozen-response-invalid")
            response_hashes.add(content_hash)
        if responses and not capture_hashes.issubset(response_hashes):
            raise ReplayError("frozen-response-missing")
        data["cutoff"] = cutoff
        canonical = {key: value for key, value in data.items()
                     if key != "declared_hash"}
        encoded = canonical_json(canonical).encode("utf-8")
        if len(encoded) > max_bytes:
            raise ReplayError("bundle-too-large")
        bundle_hash = hashlib.sha256(encoded).hexdigest()
        if data.get("declared_hash") and data["declared_hash"] != bundle_hash:
            raise ReplayError("bundle-hash-mismatch")
        return cls(data, bundle_hash)

    @property
    def ordered_documents(self):
        cutoff = _timestamp(self.data["cutoff"])
        eligible = [item for item in self.data["documents"]
                    if _timestamp(item["captured_at"]) <= cutoff]
        return sorted(eligible, key=lambda item: (
            normalize_timestamp(item["captured_at"]), str(item["source_id"]),
            str(item.get("external_id") or ""), int(item.get("version") or 1),
            fingerprint(item),
        ))

    @property
    def eligible_captures(self):
        cutoff = _timestamp(self.data["cutoff"])
        return sorted((item for item in self.data.get("captures", [])
                       if _timestamp(item["captured_at"]) <= cutoff), key=lambda item: (
            normalize_timestamp(item["captured_at"]), item["source_id"],
            item["external_id"], int(item.get("version") or 1),
        ))


@dataclass(frozen=True)
class ReplayResult:
    manifest: dict
    summary: dict
    output_directory: str = ""


class ReplayRunner:
    def __init__(self, max_items=DEFAULT_MAX_ITEMS, max_bytes=DEFAULT_MAX_BYTES,
                 batch_size=DEFAULT_BATCH_SIZE, max_passes=DEFAULT_MAX_PASSES):
        self.max_items = max(1, min(10_000, int(max_items)))
        self.max_bytes = max(1_000_000, min(1_000_000_000, int(max_bytes)))
        self.batch_size = max(1, min(500, int(batch_size)))
        self.max_passes = max(1, min(500, int(max_passes)))

    def run_fixture(self, fixture, output_directory=None):
        path = Path(fixture)
        if not path.exists():
            path = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "intelligence_replay" / f"{fixture}.json"
        bundle = ReplayBundle.load(path, self.max_items, self.max_bytes)
        return self.run(bundle, output_directory=output_directory)

    def run(self, bundle, output_directory=None):
        if not isinstance(bundle, ReplayBundle):
            bundle = ReplayBundle.validate(bundle, self.max_items, self.max_bytes)
        retained = bool(output_directory)
        temporary = None
        if retained:
            run_dir = _safe_output_directory(output_directory)
            run_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix="entity-intelligence-replay-")
            run_dir = Path(temporary.name)
        database = run_dir / "replay.db"
        clock = ReplayClock(bundle.ordered_documents[0]["captured_at"]
                            if bundle.ordered_documents else bundle.data["cutoff"])
        identity = lambda source_id, canonical_key, item: uuid5(
            NAMESPACE_URL,
            f"{bundle.data['bundle_key']}:{source_id}:{canonical_key}:{item.external_id}",
        )
        store = IntelligenceStore(
            database, clock=clock, document_id_factory=identity
        )
        stage_passes = {}
        try:
            self._register_sources(store, bundle)
            self._import_documents(store, bundle, clock)
            self._import_captures(store, bundle)
            clock.advance(bundle.data["cutoff"])
            stage_passes["world_graph"] = self._drain(
                lambda: WorldEventGraphEngine(
                    store, batch_size=self.batch_size, clock=clock
                ).run_batch().processed
            )
            stage_passes["event_fusion"] = self._drain(
                lambda: EventFusionEngine(
                    store, batch_size=self.batch_size, clock=clock
                ).run_batch().processed
            )
            comparison = EventFramingComparisonEngine(
                store, batch_size=self.batch_size, clock=clock
            ).run_batch()
            stage_passes["framing_comparison"] = 1
            assessment = CanonicalEventAssessmentEngine(
                store, batch_size=self.batch_size, clock=clock
            ).run_batch()
            stage_passes["event_assessment"] = 1
            summary = self._summary(store, bundle, comparison, assessment)
            contract = self._contract(bundle, clock)
            manifest = build_manifest(contract, summary, stage_passes)
            if retained:
                _write_json(run_dir / "manifest.json", manifest)
                _write_json(run_dir / "summary.json", summary)
            return ReplayResult(manifest, summary, str(run_dir) if retained else "")
        finally:
            if temporary is not None:
                temporary.cleanup()

    def _drain(self, operation):
        for pass_number in range(1, self.max_passes + 1):
            if int(operation() or 0) == 0:
                return pass_number
        raise ReplayError("stage-non-quiescent")

    def _register_sources(self, store, bundle):
        for source in sorted(bundle.data["sources"], key=lambda item: item["id"]):
            store.register_source(
                source["id"], source.get("name", source["id"]),
                source.get("kind", "traditional_news"),
                base_url=source.get("base_url", "https://fixture.test"),
                credibility=source.get("credibility", .5), enabled=False,
            )
            raw = dict(source["policy"])
            for key in ("allowed_hosts", "caveats", "article_hosts"):
                raw[key] = tuple(raw.get(key) or ())
            store.register_source_policy(source["id"], SourcePolicy(**raw))

    def _import_documents(self, store, bundle, clock):
        for raw in bundle.ordered_documents:
            clock.advance(raw["captured_at"])
            item = SourceItem(
                external_id=str(raw["external_id"]), title=str(raw.get("title") or ""),
                url=str(raw.get("url") or ""), summary=str(raw.get("summary") or ""),
                content=str(raw.get("content") or ""),
                published_at=raw.get("published_at"),
                category=str(raw.get("category") or "news"),
                latitude=raw.get("latitude"), longitude=raw.get("longitude"),
                metadata=dict(raw.get("metadata") or {}),
                status=str(raw.get("status") or "active"),
            )
            store.ingest_replay_item(raw["source_id"], item, raw["captured_at"])
            if raw.get("reporting_family_key"):
                with store._connect() as connection:
                    connection.execute(
                        "UPDATE documents SET reporting_family_key=? "
                        "WHERE source_id=? AND external_id=?",
                        (str(raw["reporting_family_key"])[:300], raw["source_id"],
                         raw["external_id"]),
                    )

    def _import_captures(self, store, bundle):
        responses = {str(row.get("content_hash") or ""): row.get("response", {})
                     for row in bundle.data.get("frozen_responses", [])}
        for raw in bundle.eligible_captures:
            with store._connect() as connection:
                version = connection.execute(
                    """SELECT versions.id version_id,documents.id document_id,
                              documents.publisher_key
                       FROM documents JOIN document_versions versions
                         ON versions.document_id=documents.id
                       WHERE documents.source_id=? AND documents.external_id=?
                         AND versions.version=?""",
                    (raw["source_id"], raw["external_id"],
                     int(raw.get("version") or 1)),
                ).fetchone()
                if version is None:
                    raise ReplayError("capture-document-missing")
                cursor = connection.execute(
                    """INSERT INTO article_content_captures (
                         document_id,document_version_id,source_id,original_url,
                         final_url,content_scope,normalized_text,title,byline,
                         published_at,modified_at,content_hash,word_count,status,
                         extractor,policy_version,captured_at,created_at
                       ) VALUES (?,?,?,?,?,'replay-fixture',?,?, '',NULL,NULL,?,?,
                                 'complete','replay-fixture-v1',?,?,?)""",
                    (version["document_id"], version["version_id"], raw["source_id"],
                     raw.get("url", "https://fixture.test/article"),
                     raw.get("url", "https://fixture.test/article"),
                     raw["normalized_text"], str(raw.get("title") or "")[:500],
                     raw["content_hash"], len(raw["normalized_text"].split()),
                     SOURCE_POLICY_VERSION, raw["captured_at"], raw["captured_at"]),
                )
                capture_id = cursor.lastrowid
                payload = responses.get(raw["content_hash"])
                if payload is not None:
                    observations = validate_framing(payload, raw["normalized_text"])
                    if not observations and payload.get("observations"):
                        raise ReplayError("frozen-response-invalid")
                    self._store_framing(
                        connection, capture_id, version["document_id"],
                        version["publisher_key"], raw, observations,
                    )

    def _store_framing(self, connection, capture_id, document_id, publisher,
                       capture, observations):
        scores = {}
        for item in observations:
            scores.setdefault(item["dimension"], []).append(item["strength"])
            connection.execute(
                """INSERT INTO article_framing_observations (
                     article_capture_id,document_id,publisher_key,dimension,direction,
                     strength,confidence,evidence_span,evidence_start,evidence_end,
                     explanation,method,model,input_hash,evidence_cutoff_at,created_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (capture_id, document_id, publisher, item["dimension"],
                 item["direction"], item["strength"], item["confidence"],
                 item["evidence"], item["start"], item["end"], item["explanation"],
                 FRAMING_METHOD, "frozen-replay", capture["content_hash"],
                 capture["captured_at"], capture["captured_at"]),
            )
        aggregate = {key: round(sum(values) / len(values), 4)
                     for key, values in scores.items()}
        confidence = (sum(item["confidence"] for item in observations)
                      / len(observations)) if observations else 0
        connection.execute(
            """INSERT INTO article_framing_assessments (
                 article_capture_id,publisher_key,dimension_scores,evidence_count,
                 confidence,status,method,input_hash,updated_at
               ) VALUES (?,?,?,?,?,'complete',?,?,?)""",
            (capture_id, publisher, canonical_json(aggregate), len(observations),
             round(confidence, 4), FRAMING_METHOD, capture["content_hash"],
             capture["captured_at"]),
        )

    def _contract(self, bundle, clock):
        ordered = bundle.ordered_documents
        policies = [source["policy"] for source in sorted(
            bundle.data["sources"], key=lambda item: item["id"]
        )]
        versions = {
            "source_policy": SOURCE_POLICY_VERSION,
            "claim_extraction": EXTRACTION_VERSION,
            "document_features": DOCUMENT_FEATURE_VERSION,
            "world_graph": WORLD_GRAPH_METHOD,
            "event_fusion": FUSION_METHOD,
            "event_fusion_features": FUSION_FEATURE_VERSION,
            "semantic_framing": FRAMING_METHOD,
            "framing_comparison": COMPARISON_METHOD,
            "event_assessment": ASSESSMENT_METHOD,
            "epistemic_policy": EPISTEMIC_POLICY_VERSION,
        }
        return {
            "runner_version": RUNNER_VERSION,
            "bundle_key": bundle.data["bundle_key"],
            "bundle_hash": bundle.bundle_hash,
            "cutoff": bundle.data["cutoff"],
            "ordered_evidence_hash": fingerprint(ordered),
            "evidence_counts": {
                "documents": len(ordered),
                "captures": len(bundle.eligible_captures),
                "sources": len(bundle.data["sources"]),
                "expected_gaps": len(bundle.data.get("expected_gaps", [])),
            },
            "source_policy_hash": fingerprint(policies),
            "algorithm_versions": versions,
            "configuration": {
                "batch_size": self.batch_size, "max_passes": self.max_passes,
                "max_items": self.max_items, "max_bytes": self.max_bytes,
            },
            "frozen_response_hash": fingerprint(
                bundle.data.get("frozen_responses", [])
            ),
            "logical_clock": {
                "start": normalize_timestamp(ordered[0]["captured_at"])
                if ordered else bundle.data["cutoff"],
                "end": clock.iso(),
            },
        }

    def _summary(self, store, bundle, comparison, assessment):
        with store._connect() as connection:
            def count(table):
                return int(connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0])
            counts = {
                "documents": count("documents"),
                "document_versions": count("document_versions"),
                "article_captures": count("article_content_captures"),
                "framing_assessments": count("article_framing_assessments"),
                "literal_evidence_spans": count("article_framing_observations"),
                "observations": count("world_event_observations"),
                "events": count("world_events"),
                "memberships": count("world_event_memberships"),
                "fusion_reviews": count("world_event_fusion_reviews"),
                "comparisons": count("event_publisher_comparisons"),
                "event_assessments": count("world_event_assessments"),
            }
            events = [dict(row) for row in connection.execute(
                """SELECT category,title,status,method,started_at,first_seen_at,
                          last_seen_at FROM world_events ORDER BY category,title,
                          started_at,first_seen_at"""
            )]
            memberships = [dict(row) for row in connection.execute(
                """SELECT documents.source_id,documents.external_id,
                          memberships.action,memberships.method,events.category,
                          events.title event_title
                   FROM world_event_memberships memberships
                   JOIN world_event_observations observations
                     ON observations.id=memberships.observation_id
                   JOIN documents ON documents.id=observations.document_id
                   JOIN world_events events ON events.id=memberships.world_event_id
                   WHERE memberships.active=1
                   ORDER BY documents.source_id,documents.external_id"""
            )]
            families = [dict(row) for row in connection.execute(
                """SELECT reporting_family_key,COUNT(*) count FROM documents
                   WHERE reporting_family_key!='' GROUP BY reporting_family_key
                   ORDER BY reporting_family_key"""
            )]
            fusion = [dict(row) for row in connection.execute(
                """SELECT outcome,ROUND(score,4) score,feature_version,method
                   FROM world_event_fusion_decisions
                   ORDER BY outcome,score,feature_version,method"""
            )]
        return {
            "counts": counts,
            "events": events[:500], "memberships": memberships[:2_000],
            "reporting_families": families[:500], "fusion": fusion[:2_000],
            "expected_gaps": bundle.data.get("expected_gaps", [])[:100],
            "stage_results": {
                "comparisons": int(comparison.get("comparisons", 0)),
                "event_assessments_changed": int(assessment.changed),
            },
        }


def bundle_from_database(database_path, cutoff, source_ids, max_items=2_000):
    """Export a bounded immutable-evidence bundle through a read-only handle."""
    path = Path(database_path).resolve(strict=True)
    source_ids = sorted({str(value) for value in source_ids if str(value)})
    if not source_ids:
        raise ReplayError("database-selection-required")
    cutoff = normalize_timestamp(cutoff)
    if not cutoff:
        raise ReplayError("bundle-cutoff-invalid")
    uri = f"file:{quote(str(path))}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        placeholders = ",".join("?" for _ in source_ids)
        sources = connection.execute(
            f"SELECT * FROM sources WHERE id IN ({placeholders}) ORDER BY id",
            source_ids,
        ).fetchall()
        policies = {row["source_id"]: dict(row) for row in connection.execute(
            f"SELECT * FROM source_policies WHERE source_id IN ({placeholders})",
            source_ids,
        )}
        rows = connection.execute(
            f"""SELECT documents.*,versions.version,versions.title version_title,
                       versions.summary version_summary,versions.content version_content,
                       versions.published_at version_published_at,
                       versions.metadata version_metadata,versions.captured_at
                FROM document_versions versions JOIN documents
                  ON documents.id=versions.document_id
                WHERE documents.source_id IN ({placeholders})
                  AND versions.captured_at<=?
                ORDER BY versions.captured_at,documents.source_id,
                         documents.external_id,versions.version LIMIT ?""",
            (*source_ids, cutoff, max(1, min(10_000, int(max_items)))),
        ).fetchall()
        remaining = max(0, int(max_items) - len(rows))
        captures = connection.execute(
            f"""SELECT captures.*,documents.external_id,versions.version
                FROM article_content_captures captures
                JOIN documents ON documents.id=captures.document_id
                JOIN document_versions versions
                  ON versions.id=captures.document_version_id
                WHERE documents.source_id IN ({placeholders})
                  AND captures.status='complete' AND captures.captured_at<=?
                ORDER BY captures.captured_at,documents.source_id,
                         documents.external_id,versions.version,captures.id
                LIMIT ?""",
            (*source_ids, cutoff, remaining),
        ).fetchall()
    if len(sources) != len(source_ids):
        raise ReplayError("database-source-missing")
    source_payload = []
    for row in sources:
        policy = policies.get(row["id"])
        if not policy:
            raise ReplayError("policy-snapshot-missing")
        cleaned = {key: policy[key] for key in SourcePolicy.__dataclass_fields__}
        for key in ("allowed_hosts", "caveats", "article_hosts"):
            cleaned[key] = json.loads(cleaned[key] or "[]")
        cleaned["credentials_required"] = bool(cleaned["credentials_required"])
        cleaned["article_excerpt_display"] = bool(cleaned["article_excerpt_display"])
        source_payload.append({
            "id": row["id"], "name": row["name"], "kind": row["kind"],
            "base_url": row["base_url"], "credibility": row["credibility"],
            "policy": cleaned,
        })
    documents = []
    for row in rows:
        documents.append({
            "source_id": row["source_id"], "external_id": row["external_id"],
            "version": row["version"], "title": row["version_title"],
            "url": row["url"], "summary": row["version_summary"],
            "content": row["version_content"], "category": row["category"],
            "published_at": row["version_published_at"],
            "captured_at": row["captured_at"],
            "latitude": row["latitude"], "longitude": row["longitude"],
            "metadata": json.loads(row["version_metadata"] or "{}"),
            "status": row["status"],
            "reporting_family_key": row["reporting_family_key"],
        })
    capture_payload = [{
        "source_id": row["source_id"], "external_id": row["external_id"],
        "version": row["version"], "url": row["original_url"],
        "title": row["title"], "captured_at": row["captured_at"],
        "normalized_text": row["normalized_text"],
        "content_hash": row["content_hash"],
    } for row in captures]
    return ReplayBundle.validate({
        "schema": BUNDLE_VERSION,
        "bundle_key": "database-" + fingerprint([str(path.name), cutoff, source_ids])[:16],
        "cutoff": cutoff, "sources": source_payload, "documents": documents,
        "captures": capture_payload, "frozen_responses": [], "expected_gaps": [],
        "provenance": "bounded-read-only-database-export",
    }, max_items=max_items)


def _safe_output_directory(value):
    raw = Path(value)
    if raw.exists():
        raise ReplayError("output-exists")
    resolved = raw.resolve(strict=False)
    forbidden = {Path.home().resolve(), Path(__file__).resolve().parents[2]}
    if resolved in forbidden or resolved.parent == resolved:
        raise ReplayError("unsafe-output-path")
    return resolved


def _timestamp(value):
    normalized = normalize_timestamp(value)
    if not normalized:
        raise ReplayError("timestamp-invalid")
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayError("timestamp-invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _write_json(path, value):
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description="Run isolated intelligence replay.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fixture")
    mode.add_argument("--database")
    parser.add_argument("--cutoff")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--output")
    args = parser.parse_args()
    load_dotenv(".env")
    config = IntelligenceConfig.from_env()
    try:
        runner = ReplayRunner(
            max_items=config.intelligence_replay_max_items,
            max_bytes=config.intelligence_replay_max_bytes,
            batch_size=config.intelligence_replay_batch_size,
            max_passes=config.intelligence_replay_max_passes,
        )
        if args.fixture:
            result = runner.run_fixture(args.fixture, args.output)
        else:
            if not args.cutoff or not args.source:
                raise ReplayError("database-selection-required")
            bundle = bundle_from_database(
                args.database, args.cutoff, args.source,
                max_items=config.intelligence_replay_max_items,
            )
            result = runner.run(bundle, output_directory=args.output)
    except ReplayError as exc:
        print(json.dumps({"status": "failed", "failure_code": exc.code}))
        raise SystemExit(2) from None
    print(json.dumps({
        "status": result.manifest["status"],
        "run_id": result.manifest["run_id"],
        "cutoff": result.manifest["cutoff"],
        "counts": result.summary["counts"],
        "result_fingerprint": result.manifest["result_fingerprint"],
        "output_directory": result.output_directory,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
