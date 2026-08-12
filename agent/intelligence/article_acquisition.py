"""Policy-gated, bounded capture of publisher-supplied article text."""

import hashlib
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

from agent.intelligence.store import utc_now


METHOD = "article-acquisition-v1"
EXTRACTOR = "conservative-article-html-v1"
PROCESS_SCHEDULER = "article-acquisition-processing"
ENQUEUE_SCHEDULER = "article-acquisition-enqueue"
EVENT_PROCESS_SCHEDULER = "article-acquisition-event-ready-processing"
EVENT_ENQUEUE_SCHEDULER = "article-acquisition-event-ready-enqueue"
WORKLOAD_ENGINE = "article-acquisition"


class ArticleAcquisitionEngine:
    def __init__(self, store, enabled=False, batch_size=5, timeout=15,
                 fetch_html=None, max_active_per_publisher=25,
                 max_active_global=100, fresh_window_minutes=30,
                 max_fresh_active_per_publisher=2,
                 max_fresh_active_global=10, workload_monitor=None,
                 event_ready_per_cycle=2):
        self.store = store
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(25, int(batch_size)))
        self.timeout = max(2, min(60, int(timeout)))
        self.fetch_html = fetch_html
        self.max_active_per_publisher = max(
            1, min(10_000, int(max_active_per_publisher))
        )
        self.max_active_global = max(
            1, min(100_000, int(max_active_global))
        )
        self.fresh_window_minutes = max(
            5, min(1440, int(fresh_window_minutes))
        )
        self.max_fresh_active_per_publisher = max(
            1, min(100, int(max_fresh_active_per_publisher))
        )
        self.max_fresh_active_global = max(
            1, min(1000, int(max_fresh_active_global))
        )
        self.workload_monitor = workload_monitor
        self.event_ready_per_cycle = max(
            0, min(self.batch_size, int(event_ready_per_cycle))
        )
        self.store.configure_workload_limits(
            WORKLOAD_ENGINE, self.max_active_per_publisher,
            self.max_active_global, self.max_fresh_active_per_publisher,
            self.max_fresh_active_global,
        )

    def run_batch(self):
        if not self.enabled:
            return {"enqueued": 0, "processed": 0, "captured": 0, "failed": 0}
        allowed = self._allowed_work_classes()
        if not allowed:
            return {"enqueued": 0, "processed": 0, "captured": 0,
                    "failed": 0, "shed": "disk-hard-limit"}
        self._recover_expired_leases(allowed)
        enqueued = self._enqueue()
        selected = self._select_tasks()
        captured = failed = 0
        for task in selected:
            if self._process(task):
                captured += 1
            else:
                failed += 1
            self.store.advance_scheduler_cursor(
                PROCESS_SCHEDULER, task["publisher_key"]
            )
            if task.get("is_event_ready"):
                self.store.advance_scheduler_cursor(
                    EVENT_PROCESS_SCHEDULER, task["publisher_key"]
                )
        return {"enqueued": enqueued, "processed": len(selected),
                "captured": captured, "failed": failed}

    def _allowed_work_classes(self):
        if self.workload_monitor is None:
            return ("fresh", "backfill")
        return self.workload_monitor.allowed_work_classes()

    def _recover_expired_leases(self, allowed_classes=("fresh", "backfill")):
        now = utc_now()
        placeholders = ",".join("?" for _ in allowed_classes)
        with self.store._connect() as connection:
            expired = connection.execute(
                f"""SELECT id FROM article_acquisition_tasks
                   WHERE status='running' AND lease_expires_at IS NOT NULL
                     AND lease_expires_at<=?
                     AND work_class IN ({placeholders})""",
                (now, *allowed_classes),
            ).fetchall()
            if not expired:
                return 0
            task_ids = [int(row[0]) for row in expired]
            placeholders = ",".join("?" for _ in task_ids)
            connection.execute(
                f"""UPDATE article_extraction_attempts
                    SET status='failed',error_code='ProcessInterrupted',
                        finished_at=?
                    WHERE status='started' AND task_id IN ({placeholders})""",
                (now, *task_ids),
            )
            connection.execute(
                f"""UPDATE article_acquisition_tasks
                    SET status='retry',next_attempt_at=?,lease_expires_at=NULL,
                        last_error='lease-expired',updated_at=?
                    WHERE id IN ({placeholders})""",
                (now, now, *task_ids),
            )
        return len(task_ids)

    def _select_tasks(self):
        now = utc_now()
        allowed = self._allowed_work_classes()
        if not allowed:
            return []
        placeholders = ",".join("?" for _ in allowed)
        with self.store._connect() as connection:
            event_ready_ids = self._event_ready_task_ids(
                connection, now, allowed
            )
            ready_expression = "0"
            ready_parameters = []
            if event_ready_ids:
                ready_placeholders = ",".join("?" for _ in event_ready_ids)
                ready_expression = f"tasks.id IN ({ready_placeholders})"
                ready_parameters = list(event_ready_ids)
            rows = connection.execute(
                f"""WITH eligible AS (
                     SELECT tasks.*,policies.article_hosts,
                            policies.article_max_bytes,policies.retention_days,
                            policies.article_requests_per_cycle,
                            COALESCE(NULLIF(documents.publisher_key,''),
                                     tasks.source_id) publisher_key,
                            {ready_expression} is_event_ready,
                            ROW_NUMBER() OVER (
                              PARTITION BY COALESCE(
                                NULLIF(documents.publisher_key,''),tasks.source_id)
                              ORDER BY CASE
                                         WHEN tasks.work_class='fresh' THEN 0
                                         WHEN tasks.priority>=2 THEN 1
                                         WHEN tasks.status='retry' THEN 2
                                         ELSE 3
                                       END,
                                       tasks.next_attempt_at,tasks.id
                            ) publisher_rank
                     FROM article_acquisition_tasks tasks
                     JOIN documents ON documents.id=tasks.document_id
                     JOIN source_policies policies
                       ON policies.source_id=tasks.source_id
                     WHERE tasks.status IN ('pending','retry')
                       AND tasks.next_attempt_at<=?
                       AND tasks.work_class IN ({placeholders})
                   ) SELECT * FROM eligible WHERE publisher_rank<=?
                     ORDER BY publisher_key,publisher_rank""",
                (*ready_parameters, now, *allowed, self.batch_size),
            ).fetchall()
        buckets = {}
        for raw in rows:
            task = dict(raw)
            buckets.setdefault(task["publisher_key"], []).append(task)
        publishers = _rotated_keys(
            buckets, self.store.scheduler_cursor(PROCESS_SCHEDULER)
        )
        selected = []
        per_source = {}
        seen = set()

        def take(predicate, maximum):
            lane = {
                publisher: [task for task in buckets[publisher]
                            if predicate(task)]
                for publisher in publishers
            }
            rank = 0
            lane_depth = max((len(bucket) for bucket in lane.values()), default=0)
            while len(selected) < maximum and rank < lane_depth:
                for publisher in publishers:
                    bucket = lane[publisher]
                    if rank >= len(bucket):
                        continue
                    task = bucket[rank]
                    if task["id"] in seen:
                        continue
                    source_id = task["source_id"]
                    cap = max(0, int(
                        task.get("article_requests_per_cycle") or 0
                    ))
                    if not cap or per_source.get(source_id, 0) >= cap:
                        continue
                    per_source[source_id] = per_source.get(source_id, 0) + 1
                    seen.add(task["id"])
                    selected.append(task)
                    if len(selected) >= maximum:
                        break
                rank += 1

        if any(task["work_class"] == "fresh" for task in rows):
            take(lambda task: task["work_class"] == "fresh", 1)
        ready_target = min(
            self.batch_size, len(selected) + self.event_ready_per_cycle
        )
        take(lambda task: bool(task.get("is_event_ready")), ready_target)
        take(lambda task: True, self.batch_size)
        return selected

    def _event_ready_task_ids(self, connection, now, allowed_classes):
        """Resolve event-ready tasks once instead of once per queued task."""
        placeholders = ",".join("?" for _ in allowed_classes)
        rows = connection.execute(
            f"""SELECT DISTINCT id FROM (
                 SELECT tasks.id
                 FROM article_acquisition_tasks tasks
                 JOIN documents
                   ON documents.id=tasks.document_id
                 JOIN world_event_observations own_observation
                   ON own_observation.document_version_id=
                      tasks.document_version_id
                  AND own_observation.status='active'
                 JOIN world_event_memberships own_membership
                   ON own_membership.observation_id=own_observation.id
                  AND own_membership.active=1
                 JOIN world_events event
                   ON event.id=own_membership.world_event_id
                  AND event.status='active'
                 JOIN world_event_memberships peer_membership
                   ON peer_membership.world_event_id=event.id
                  AND peer_membership.active=1
                 JOIN world_event_observations peer_observation
                   ON peer_observation.id=peer_membership.observation_id
                  AND peer_observation.status='active'
                 JOIN documents peer_document
                   ON peer_document.id=peer_observation.document_id
                 JOIN document_versions peer_version
                   ON peer_version.id=peer_observation.document_version_id
                 JOIN sources peer_source
                   ON peer_source.id=peer_observation.source_id
                 LEFT JOIN source_policies peer_policy
                   ON peer_policy.source_id=peer_observation.source_id
                 LEFT JOIN article_content_captures peer_capture
                   ON peer_capture.document_version_id=
                      peer_observation.document_version_id
                  AND peer_capture.status='complete'
                 LEFT JOIN article_framing_assessments peer_assessment
                   ON peer_assessment.article_capture_id=peer_capture.id
                  AND peer_assessment.status='complete'
                 WHERE tasks.status IN ('pending','retry')
                   AND tasks.next_attempt_at<=?
                   AND tasks.work_class IN ({placeholders})
                 GROUP BY tasks.id,event.id,documents.publisher_key
                 HAVING COUNT(DISTINCT peer_document.publisher_key)>=2
                    AND COUNT(DISTINCT COALESCE(
                      NULLIF(peer_document.reporting_family_key,''),
                      NULLIF(peer_document.publisher_key,''),
                      peer_document.source_id))>=2
                    AND COUNT(DISTINCT peer_assessment.publisher_key)<2
                    AND COUNT(DISTINCT CASE WHEN
                      peer_assessment.status='complete' OR
                      (peer_capture.status='complete' AND
                       peer_capture.word_count>=80) OR
                      (peer_capture.id IS NULL AND
                       (peer_policy.article_acquisition_mode='publisher-page' OR
                        (peer_version.metadata LIKE
                          '%publisher_feed_full_content%' AND
                         length(peer_version.content)>=500)) AND
                       COALESCE(peer_source.last_error,'')='')
                      THEN peer_document.publisher_key END)>=2
                    AND SUM(CASE WHEN peer_assessment.publisher_key=
                         documents.publisher_key THEN 1 ELSE 0 END)=0
               ) LIMIT 5000""",
            (now, *allowed_classes),
        ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def _enqueue(self):
        now = utc_now()
        count = 0
        last_rotation_key = ""
        with self.store._connect() as connection:
            active_rows = connection.execute(
                """SELECT COALESCE(NULLIF(documents.publisher_key,''),
                                   tasks.source_id) publisher_key,
                          SUM(tasks.work_class!='fresh') active_tasks,
                          SUM(tasks.work_class='fresh') fresh_active_tasks
                   FROM article_acquisition_tasks tasks
                   JOIN documents ON documents.id=tasks.document_id
                   WHERE tasks.status IN ('pending','retry','running')
                   GROUP BY COALESCE(NULLIF(documents.publisher_key,''),
                                     tasks.source_id)"""
            ).fetchall()
            active = {str(row[0]): int(row[1] or 0) for row in active_rows}
            active_global = sum(active.values())
            fresh_active = {str(row[0]): int(row[2] or 0) for row in active_rows}
            fresh_active_global = sum(fresh_active.values())
            event_rows = self._event_ready_enqueue_candidates(
                connection, self.event_ready_per_cycle
            )
            policies = connection.execute(
                """SELECT sources.id source_id,
                          policies.article_acquisition_mode,
                          policies.article_requests_per_cycle
                   FROM sources JOIN source_policies policies
                     ON policies.source_id=sources.id
                   WHERE sources.kind='traditional_news'
                   ORDER BY sources.id"""
            ).fetchall()
            buckets = {}
            for policy in policies:
                per_source = max(
                    5, int(policy["article_requests_per_cycle"] or 0) * 5
                )
                bucket = connection.execute(
                    """SELECT versions.id version_id,versions.document_id,
                              versions.content,versions.content_hash,
                              versions.metadata,documents.source_id,documents.url,
                              documents.retrieved_at,
                              COALESCE(NULLIF(documents.publisher_key,''),
                                       documents.source_id) publisher_key,
                              CASE WHEN julianday(documents.retrieved_at)>=
                                julianday('now',?) THEN 1 ELSE 0 END is_fresh,
                              policies.article_acquisition_mode,
                              policies.policy_version,policies.retention_days
                       FROM documents
                       JOIN document_versions versions
                         ON versions.document_id=documents.id
                       JOIN source_policies policies
                         ON policies.source_id=documents.source_id
                       WHERE documents.source_id=?
                         AND (
                           policies.article_acquisition_mode='publisher-page' OR
                           versions.metadata LIKE '%publisher_feed_full_content%'
                         )
                         AND versions.id=(
                           SELECT MAX(other.id) FROM document_versions other
                           WHERE other.document_id=versions.document_id
                         )
                         AND NOT EXISTS (
                           SELECT 1 FROM article_content_captures capture
                           WHERE capture.document_version_id=versions.id
                         )
                         AND NOT EXISTS (
                           SELECT 1 FROM article_acquisition_tasks task
                           WHERE task.document_version_id=versions.id
                             AND task.method=?
                         )
                       ORDER BY is_fresh DESC,versions.id LIMIT ?""",
                    (
                        f"-{self.fresh_window_minutes} minutes",
                        policy["source_id"], METHOD, per_source,
                    ),
                ).fetchall()
                for raw in bucket:
                    buckets.setdefault(raw["publisher_key"], []).append(raw)
            rows = []
            rank = 0
            maximum = self.batch_size * 5
            publishers = _rotated_keys(
                buckets, self.store.scheduler_cursor(ENQUEUE_SCHEDULER)
            )
            while len(rows) < maximum:
                added = False
                for publisher in publishers:
                    bucket = buckets[publisher]
                    if rank < len(bucket):
                        rows.append(bucket[rank])
                        added = True
                        if len(rows) >= maximum:
                            break
                if not added:
                    break
                rank += 1
            event_buckets = {}
            event_pairs = set()
            for raw in event_rows:
                pair = (raw["event_id"], raw["publisher_key"])
                if pair in event_pairs:
                    continue
                event_pairs.add(pair)
                event_buckets.setdefault(raw["publisher_key"], []).append(raw)
            event_publishers = _rotated_keys(
                event_buckets,
                self.store.scheduler_cursor(EVENT_ENQUEUE_SCHEDULER),
            )
            event_selected = []
            rank = 0
            while len(event_selected) < self.event_ready_per_cycle:
                added = False
                for publisher in event_publishers:
                    bucket = event_buckets[publisher]
                    if rank < len(bucket):
                        event_selected.append(bucket[rank])
                        added = True
                        if len(event_selected) >= self.event_ready_per_cycle:
                            break
                if not added:
                    break
                rank += 1
            maximum = self.batch_size * 5
            seen_versions = set()
            last_event_rotation_key = ""
            for raw in [*event_selected, *rows]:
                if count >= maximum:
                    break
                row = dict(raw)
                if row["version_id"] in seen_versions:
                    continue
                seen_versions.add(row["version_id"])
                work_class = "fresh" if row["is_fresh"] else "backfill"
                if work_class not in self._allowed_work_classes():
                    continue
                metadata = self.store._json_load(row["metadata"], {})
                if (
                    metadata.get("content_scope") == "publisher_feed_full_content"
                    and len(str(row["content"] or "")) >= 500
                ):
                    self._store_capture(
                        connection, row, row["url"], row["url"], row["content"],
                        "publisher-feed-full-content", {}, now,
                    )
                    count += 1
                    last_rotation_key = row["publisher_key"]
                elif row["article_acquisition_mode"] == "publisher-page":
                    publisher_key = row["publisher_key"]
                    if work_class == "fresh":
                        if (
                            fresh_active_global >= self.max_fresh_active_global
                            or fresh_active.get(publisher_key, 0)
                            >= self.max_fresh_active_per_publisher
                        ):
                            continue
                    elif (
                        active_global >= self.max_active_global
                        or active.get(publisher_key, 0)
                        >= self.max_active_per_publisher
                    ):
                        continue
                    connection.execute(
                        """INSERT INTO article_acquisition_tasks (
                             document_id,document_version_id,source_id,article_url,
                             status,priority,next_attempt_at,policy_version,method,
                             created_at,updated_at,work_class
                           ) VALUES (?,?,?,?,'pending',?,?,?,?,?,?,?)""",
                        (row["document_id"], row["version_id"], row["source_id"],
                         row["url"], (2.0 if row.get("is_event_ready") else
                                      1.0 if work_class == "fresh" else .5),
                         now, row["policy_version"], METHOD, now, now, work_class),
                    )
                    if work_class == "fresh":
                        fresh_active[publisher_key] = (
                            fresh_active.get(publisher_key, 0) + 1
                        )
                        fresh_active_global += 1
                    else:
                        active[publisher_key] = active.get(publisher_key, 0) + 1
                        active_global += 1
                    count += 1
                    last_rotation_key = publisher_key
                if row.get("is_event_ready"):
                    last_event_rotation_key = row["publisher_key"]
        if last_rotation_key:
            self.store.advance_scheduler_cursor(
                ENQUEUE_SCHEDULER, last_rotation_key
            )
        if last_event_rotation_key:
            self.store.advance_scheduler_cursor(
                EVENT_ENQUEUE_SCHEDULER, last_event_rotation_key
            )
        return count

    def _event_ready_enqueue_candidates(self, connection, limit):
        if limit <= 0:
            return []
        rows = connection.execute(
            """WITH event_stats AS (
                 SELECT event.id event_id,
                        COUNT(DISTINCT peer_document.publisher_key) publishers,
                        COUNT(DISTINCT COALESCE(
                          NULLIF(peer_document.reporting_family_key,''),
                          NULLIF(peer_document.publisher_key,''),
                          peer_document.source_id)) families,
                        COUNT(DISTINCT peer_assessment.publisher_key) assessed
                 FROM world_events event
                 JOIN world_event_memberships peer_membership
                   ON peer_membership.world_event_id=event.id
                  AND peer_membership.active=1
                 JOIN world_event_observations peer_observation
                   ON peer_observation.id=peer_membership.observation_id
                  AND peer_observation.status='active'
                 JOIN documents peer_document
                   ON peer_document.id=peer_observation.document_id
                 JOIN document_versions peer_version
                   ON peer_version.id=peer_observation.document_version_id
                 JOIN sources peer_source
                   ON peer_source.id=peer_observation.source_id
                 LEFT JOIN source_policies peer_policy
                   ON peer_policy.source_id=peer_observation.source_id
                 LEFT JOIN article_content_captures peer_capture
                   ON peer_capture.document_version_id=
                      peer_observation.document_version_id
                  AND peer_capture.status='complete'
                 LEFT JOIN article_framing_assessments peer_assessment
                   ON peer_assessment.article_capture_id=peer_capture.id
                  AND peer_assessment.status='complete'
                 WHERE event.status='active'
                 GROUP BY event.id
                 HAVING publishers>=2 AND families>=2 AND assessed<2
                    AND COUNT(DISTINCT CASE WHEN
                      peer_assessment.status='complete' OR
                      (peer_capture.status='complete' AND
                       peer_capture.word_count>=80) OR
                      (peer_capture.id IS NULL AND
                       (peer_policy.article_acquisition_mode='publisher-page' OR
                        (peer_version.metadata LIKE
                          '%publisher_feed_full_content%' AND
                         length(peer_version.content)>=500)) AND
                       COALESCE(peer_source.last_error,'')='')
                      THEN peer_document.publisher_key END)>=2
               ) SELECT DISTINCT stats.event_id,
                        versions.id version_id,versions.document_id,
                        versions.content,versions.content_hash,versions.metadata,
                        documents.source_id,documents.url,documents.retrieved_at,
                        COALESCE(NULLIF(documents.publisher_key,''),
                                 documents.source_id) publisher_key,
                        CASE WHEN julianday(documents.retrieved_at)>=
                          julianday('now',?) THEN 1 ELSE 0 END is_fresh,
                        policies.article_acquisition_mode,
                        policies.policy_version,policies.retention_days,
                        1 is_event_ready,observation.captured_at
                 FROM event_stats stats
                 JOIN world_event_memberships membership
                   ON membership.world_event_id=stats.event_id
                  AND membership.active=1
                 JOIN world_event_observations observation
                   ON observation.id=membership.observation_id
                  AND observation.status='active'
                 JOIN document_versions versions
                   ON versions.id=observation.document_version_id
                 JOIN documents ON documents.id=observation.document_id
                 JOIN sources ON sources.id=observation.source_id
                 JOIN source_policies policies
                   ON policies.source_id=observation.source_id
                 WHERE COALESCE(sources.last_error,'')=''
                   AND (policies.article_acquisition_mode='publisher-page' OR
                        (versions.metadata LIKE
                          '%publisher_feed_full_content%' AND
                         length(versions.content)>=500))
                   AND NOT EXISTS (
                     SELECT 1 FROM article_content_captures capture
                     WHERE capture.document_version_id=versions.id)
                   AND NOT EXISTS (
                     SELECT 1 FROM article_acquisition_tasks task
                     WHERE task.document_version_id=versions.id
                       AND task.method=?)
                   AND NOT EXISTS (
                     SELECT 1 FROM world_event_memberships assessed_membership
                     JOIN world_event_observations assessed_observation
                       ON assessed_observation.id=assessed_membership.observation_id
                     JOIN documents assessed_document
                       ON assessed_document.id=assessed_observation.document_id
                     JOIN article_content_captures assessed_capture
                       ON assessed_capture.document_version_id=
                          assessed_observation.document_version_id
                      AND assessed_capture.status='complete'
                     JOIN article_framing_assessments assessment
                       ON assessment.article_capture_id=assessed_capture.id
                      AND assessment.status='complete'
                     WHERE assessed_membership.world_event_id=stats.event_id
                       AND assessed_membership.active=1
                       AND assessed_document.publisher_key=documents.publisher_key)
                 ORDER BY observation.captured_at,stats.event_id,publisher_key,
                          versions.id LIMIT ?""",
            (f"-{self.fresh_window_minutes} minutes", METHOD,
             min(5000, max(limit * 100, limit))),
        ).fetchall()
        return rows

    def _process(self, task):
        now = utc_now()
        with self.store._connect() as connection:
            attempt_id = connection.execute(
                """INSERT INTO article_extraction_attempts
                     (task_id,status,started_at) VALUES (?,'started',?)""",
                (task["id"], now),
            ).lastrowid
            connection.execute(
                """UPDATE article_acquisition_tasks SET status='running',
                     lease_expires_at=?,attempt_count=attempt_count+1,updated_at=?
                   WHERE id=?""",
                (_future(minutes=5), now, task["id"]),
            )
        hosts = self.store._json_load(task.get("article_hosts"), [])
        maximum = max(1, min(5_000_000, int(task.get("article_max_bytes") or 0)))
        try:
            response = (
                self.fetch_html(task["article_url"], hosts, maximum)
                if self.fetch_html else
                _fetch(task["article_url"], hosts, maximum, self.timeout)
            )
            final_url = str(response.get("final_url") or task["article_url"])
            _validate_url(final_url, hosts)
            body = response.get("body") or b""
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            article = _extract_article(str(body))
            if len(article["text"]) < 200:
                raise ArticleUnavailable("insufficient-article-text")
            with self.store._connect() as connection:
                version = connection.execute(
                    """SELECT versions.id version_id,versions.document_id,
                              versions.content_hash,documents.source_id,documents.url
                       FROM document_versions versions
                       JOIN documents ON documents.id=versions.document_id
                       WHERE versions.id=?""", (task["document_version_id"],)
                ).fetchone()
                self._store_capture(
                    connection, dict(version), task["article_url"], final_url,
                    article["text"], "publisher-article-page",
                    {**response.get("headers", {}), **article}, now,
                    retention_days=task.get("retention_days"),
                    policy_version=task["policy_version"],
                )
                connection.execute(
                    """UPDATE article_acquisition_tasks SET status='complete',
                       lease_expires_at=NULL,last_error='',updated_at=? WHERE id=?""",
                    (now, task["id"]),
                )
                connection.execute(
                    """UPDATE article_extraction_attempts SET status='complete',
                       http_status=?,response_bytes=?,final_url=?,finished_at=?
                       WHERE id=?""",
                    (int(response.get("status") or 200), len(str(body).encode()),
                     final_url, now, attempt_id),
                )
            return True
        except Exception as exc:
            code = str(exc)[:120] or type(exc).__name__
            permanent = isinstance(exc, (ArticleBlocked, ArticleUnavailable))
            with self.store._connect() as connection:
                connection.execute(
                    """UPDATE article_acquisition_tasks SET status=?,
                       next_attempt_at=?,lease_expires_at=NULL,last_error=?,updated_at=?
                       WHERE id=?""",
                    ("blocked" if permanent else "retry", _future(hours=6),
                     code, now, task["id"]),
                )
                connection.execute(
                    """UPDATE article_extraction_attempts SET status=?,error_code=?,
                       finished_at=? WHERE id=?""",
                    ("blocked" if permanent else "failed", code, now, attempt_id),
                )
            return False

    def _store_capture(self, connection, row, original_url, final_url, text,
                       scope, metadata, now, retention_days=None,
                       policy_version=None):
        normalized = _normalize(text)
        content_hash = hashlib.sha256(normalized.encode()).hexdigest()
        retention = (
            _future(days=int(retention_days)) if retention_days else None
        )
        connection.execute(
            """INSERT OR IGNORE INTO article_content_captures (
                 document_id,document_version_id,source_id,original_url,final_url,
                 content_scope,normalized_text,title,byline,published_at,modified_at,
                 content_hash,word_count,http_etag,http_last_modified,status,
                 extractor,policy_version,retention_expires_at,captured_at,created_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["document_id"], row["version_id"], row["source_id"], original_url,
             final_url, scope, normalized, str(metadata.get("title") or "")[:500],
             str(metadata.get("byline") or "")[:300], metadata.get("published_at"),
             metadata.get("modified_at"), content_hash, len(normalized.split()),
             str(metadata.get("etag") or "")[:300],
             str(metadata.get("last_modified") or "")[:300], "complete", EXTRACTOR,
             policy_version or "source-contract-v2", retention, now, now),
        )
        connection.execute(
            """UPDATE document_enrichments SET status='article-derived-pending',
               updated_at=? WHERE document_version_id=?""",
            (now, row["version_id"]),
        )


class ArticleBlocked(ValueError):
    pass


class ArticleUnavailable(ValueError):
    pass


def _fetch(url, hosts, maximum, timeout):
    _validate_url(url, hosts)
    request = urllib.request.Request(url, headers={
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "EntityIntelligence/0.2 (bounded local article analysis)",
    })
    opener = urllib.request.build_opener(_RedirectValidator(hosts))
    try:
        with opener.open(request, timeout=timeout) as response:
            content_type = str(response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                raise ArticleUnavailable("unsupported-content-type")
            declared = int(response.headers.get("Content-Length") or 0)
            if declared and declared > maximum:
                raise ArticleUnavailable("oversized-article")
            body = response.read(maximum + 1)
            if len(body) > maximum:
                raise ArticleUnavailable("oversized-article")
            return {"body": body, "final_url": response.geturl(),
                    "status": response.status,
                    "headers": {"etag": response.headers.get("ETag", ""),
                                "last_modified": response.headers.get("Last-Modified", "")}}
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403, 407, 451}:
            raise ArticleBlocked(f"access-blocked-{exc.code}") from exc
        raise


class _RedirectValidator(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url, hosts):
    parsed = urllib.parse.urlsplit(str(url))
    host = str(parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ArticleBlocked("unsafe-article-url")
    if not host or not any(host == allowed or host.endswith("." + allowed)
                           for allowed in hosts):
        raise ArticleBlocked("article-host-not-allowed")
    if host.endswith(".test"):
        return
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443)}
    except OSError as exc:
        raise ArticleUnavailable("article-host-unresolved") from exc
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ArticleBlocked("article-host-not-public")


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip = 0
        self.text = []
        self.title = ""
        self._in_title = False
        self.json_ld = []
        self._json_script = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        values = dict(attrs)
        if tag in {"script", "style", "nav", "header", "footer", "aside", "form"}:
            self.skip += 1
        if tag == "script" and values.get("type") == "application/ld+json":
            self._json_script = True
        if tag in {"article", "main"}:
            self.depth += 1
        if tag == "title":
            self._in_title = True
        if self.depth and tag in {"p", "h1", "h2", "li", "blockquote"}:
            self.text.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"article", "main"} and self.depth:
            self.depth -= 1
        if tag in {"script", "style", "nav", "header", "footer", "aside", "form"} and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._json_script = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._json_script:
            self.json_ld.append(data)
        if self.depth and not self.skip:
            self.text.append(data)


def _extract_article(html):
    parser = _ArticleParser()
    parser.feed(html[:5_000_000])
    structured = ""
    byline = published = modified = ""
    for block in parser.json_ld:
        try:
            payload = json.loads(block)
        except (TypeError, ValueError):
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for item in entries:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                entries.extend(item["@graph"])
            body = item.get("articleBody")
            if isinstance(body, str) and len(body) > len(structured):
                structured = body
                author = item.get("author")
                if isinstance(author, dict):
                    byline = str(author.get("name") or "")
                published = str(item.get("datePublished") or "")
                modified = str(item.get("dateModified") or "")
    return {"text": _normalize(structured or " ".join(parser.text)),
            "title": _normalize(parser.title)[:500], "byline": byline[:300],
            "published_at": published or None, "modified_at": modified or None}


def _normalize(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:200_000]


def _future(minutes=0, hours=0, days=0):
    return (datetime.now(UTC) + timedelta(
        minutes=minutes, hours=hours, days=days
    )).isoformat().replace("+00:00", "Z")


def _rotated_keys(buckets, cursor):
    keys = sorted(buckets)
    if not keys or not cursor:
        return keys
    for index, key in enumerate(keys):
        if key > cursor:
            return keys[index:] + keys[:index]
    return keys
