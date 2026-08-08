"""Safely evaluate historical clustering against a disposable database copy."""

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from agent.intelligence.clustering import EventClusterer
from agent.intelligence.config import IntelligenceConfig
from agent.intelligence.features import extract_document_features
from agent.intelligence.store import IntelligenceStore


def dry_run(database_path, limit=0, sample_limit=10):
    source_path = Path(database_path)
    # Applying schema migrations is safe and required for the running version;
    # all clustering evaluation after that happens on a disposable backup.
    IntelligenceStore(source_path)
    with tempfile.TemporaryDirectory(prefix="entity-cluster-dry-run-") as temp:
        copy_path = Path(temp) / "intelligence.db"
        with sqlite3.connect(source_path) as source, sqlite3.connect(copy_path) as copy:
            source.backup(copy)
        store = IntelligenceStore(copy_path)
        config = IntelligenceConfig.from_env()
        clusterer = EventClusterer(
            auto_link_threshold=config.cluster_auto_link_threshold,
            review_threshold=config.cluster_review_threshold,
            lookback_days=config.cluster_lookback_days,
            max_candidates=config.cluster_max_candidates
        )
        with store._connect() as connection:
            query = """
                SELECT documents.*, situation_documents.situation_id
                FROM documents
                JOIN situation_documents
                  ON situation_documents.document_id = documents.id
                WHERE documents.status = 'active'
                ORDER BY COALESCE(documents.published_at,
                                  documents.retrieved_at) ASC
            """
            params = []
            if limit:
                query += " LIMIT ?"
                params.append(max(1, int(limit)))
            rows = [dict(row) for row in connection.execute(query, params)]
            for document in rows:
                document["metadata"] = store._json_load(
                    document.get("metadata"), {}
                )
                clusterer._store_features(
                    connection, document["id"],
                    extract_document_features(document)
                )

            summary = {
                "mode": "dry-run",
                "documents_scanned": len(rows),
                "already_clustered": 0,
                "proposed_auto_links": 0,
                "review_candidates": 0,
                "separate": 0,
                "auto_link_samples": [],
                "review_samples": []
            }
            for document in rows:
                decision = clusterer.decide(connection, document)
                if decision.target_situation_id == document["situation_id"]:
                    summary["already_clustered"] += 1
                    continue
                if decision.action == "link":
                    summary["proposed_auto_links"] += 1
                    samples = summary["auto_link_samples"]
                elif decision.action == "review":
                    summary["review_candidates"] += 1
                    samples = summary["review_samples"]
                else:
                    summary["separate"] += 1
                    continue
                if len(samples) < max(0, int(sample_limit)):
                    samples.append({
                        "document_id": document["id"],
                        "title": document["title"],
                        "current_situation_id": document["situation_id"],
                        "target_situation_id": decision.target_situation_id,
                        "action": decision.action,
                        "score": decision.score,
                        "components": decision.components,
                        "relationship": decision.relationship
                    })
        return summary


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate historical situation clustering without modifying it."
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sample-limit", type=int, default=10)
    args = parser.parse_args()
    load_dotenv(".env")
    config = IntelligenceConfig.from_env()
    print(json.dumps(
        dry_run(
            config.database_path,
            limit=args.limit,
            sample_limit=args.sample_limit
        ), indent=2
    ))


if __name__ == "__main__":
    main()
