"""Durable workload health and article-pipeline load shedding."""

import shutil
from datetime import UTC, datetime


ENGINE = "article-acquisition"
POLICY_VERSION = "article-workload-v1"
SOFT_LIMIT_DEFAULT = 2_147_483_648
HARD_LIMIT_DEFAULT = 3_221_225_472


class WorkloadMonitor:
    def __init__(self, store, window_minutes=60,
                 disk_soft_limit_bytes=SOFT_LIMIT_DEFAULT,
                 disk_hard_limit_bytes=HARD_LIMIT_DEFAULT,
                 size_reader=None, free_reader=None, clock=None):
        self.store = store
        self.window_minutes = max(15, min(1440, int(window_minutes)))
        self.soft_limit = int(disk_soft_limit_bytes)
        self.hard_limit = int(disk_hard_limit_bytes)
        self.size_reader = size_reader or _file_size
        self.free_reader = free_reader or _filesystem_free
        self.clock = clock or (lambda: datetime.now(UTC))
        self._state = {"status": "unknown", "reason": "not-yet-checked"}

    @property
    def state(self):
        return dict(self._state)

    def allows_fresh_pages(self):
        return self._state["status"] != "disk-hard-limit"

    def allows_backfill_pages(self):
        return self._state["status"] in {
            "healthy", "draining", "backpressure-active"
        }

    def allowed_work_classes(self):
        if not self.allows_fresh_pages():
            return ()
        if self.allows_backfill_pages():
            return ("fresh", "backfill")
        return ("fresh",)

    def refresh(self):
        now_dt = self.clock()
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=UTC)
        checked_at = now_dt.astimezone(UTC).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z")
        queue = self.store.workload_queue_metrics(
            self.window_minutes, now=now_dt
        )
        storage, storage_known = self._storage_metrics()
        status, reason = self._classify(storage, storage_known, queue)
        metrics = {"storage": storage, "queue": queue,
                   "window_minutes": self.window_minutes}
        self.store.record_workload_state(
            ENGINE, status, reason, metrics, POLICY_VERSION,
            checked_at=checked_at,
        )
        self._state = {"status": status, "reason": reason,
                       "checked_at": checked_at}
        return self.state

    def _storage_metrics(self):
        path = self.store.path
        sizes = {}
        known = True
        for label, candidate, required in (
            ("database_bytes", path, True),
            ("wal_bytes", path.with_name(path.name + "-wal"), False),
            ("shm_bytes", path.with_name(path.name + "-shm"), False),
        ):
            try:
                sizes[label] = max(0, int(self.size_reader(candidate)))
            except FileNotFoundError:
                sizes[label] = 0
                known = known and not required
            except (OSError, TypeError, ValueError):
                sizes[label] = None
                known = False
        numeric = [value for value in sizes.values() if isinstance(value, int)]
        sizes["combined_bytes"] = sum(numeric) if known else None
        sizes["soft_limit_bytes"] = self.soft_limit
        sizes["hard_limit_bytes"] = self.hard_limit
        try:
            sizes["filesystem_free_bytes"] = max(
                0, int(self.free_reader(path.parent))
            )
        except (OSError, TypeError, ValueError):
            sizes["filesystem_free_bytes"] = None
        return sizes, known

    def _classify(self, storage, storage_known, queue):
        if not storage_known or storage["combined_bytes"] is None:
            return "unknown", "storage-metrics-unavailable"
        combined = storage["combined_bytes"]
        if combined >= self.hard_limit:
            return "disk-hard-limit", "disk-hard-limit-reached"
        if combined >= self.soft_limit:
            return "disk-soft-limit", "disk-soft-limit-reached"
        if not queue.get("limits_known"):
            return "unknown", "workload-limits-unavailable"
        if queue["over_ceiling"] and queue["recent_completions"] > 0:
            return "draining", "queue-over-ceiling-with-progress"
        if queue["at_ceiling"]:
            return "backpressure-active", "queue-ceiling-reached"
        return "healthy", "within-workload-limits"


def _file_size(path):
    return path.stat().st_size


def _filesystem_free(path):
    return shutil.disk_usage(path).free
