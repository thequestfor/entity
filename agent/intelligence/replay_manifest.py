"""Canonical, privacy-bounded manifests for isolated intelligence replay."""

import hashlib
import json


MANIFEST_VERSION = "intelligence-replay-manifest-v1"


def canonical_json(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_manifest(contract, summary, stage_passes, status="complete",
                   failure_code=""):
    stable = {
        "manifest_version": MANIFEST_VERSION,
        "runner_version": contract["runner_version"],
        "bundle_key": contract["bundle_key"],
        "bundle_hash": contract["bundle_hash"],
        "cutoff": contract["cutoff"],
        "ordered_evidence_hash": contract["ordered_evidence_hash"],
        "evidence_counts": contract["evidence_counts"],
        "source_policy_hash": contract["source_policy_hash"],
        "algorithm_versions": contract["algorithm_versions"],
        "configuration": contract["configuration"],
        "frozen_response_hash": contract["frozen_response_hash"],
        "logical_clock": contract["logical_clock"],
        "stage_passes": stage_passes,
        "status": status,
        "failure_code": str(failure_code or "")[:120],
        "result_fingerprint": fingerprint(summary) if status == "complete" else "",
    }
    stable["run_id"] = fingerprint({
        key: value for key, value in stable.items()
        if key not in {"result_fingerprint", "status", "failure_code"}
    })
    return stable
