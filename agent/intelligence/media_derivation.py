"""Bounded derivation of text evidence from explicitly cached public media."""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from agent.intelligence.store import utc_now


METHOD = "public-media-derivation-v1"
LANE = "public-media-versions-v1"


@dataclass(frozen=True)
class MediaDerivationResult:
    processed: int = 0
    completed: int = 0
    unavailable: int = 0
    failed: int = 0


class LocalMediaProcessor:
    """Use bounded local tools when installed; otherwise fail closed."""

    def __init__(self, timeout=45, whisper_model=None):
        self.timeout = max(5, min(180, int(timeout)))
        self.whisper_model = Path(whisper_model).resolve() if whisper_model else None

    def derive(self, path, mime_type="", media_type=""):
        mime = str(mime_type or "").lower()
        kind = str(media_type or "").lower()
        if mime.startswith("image/") or "photo" in kind:
            text = self._ocr(path)
            return [_item("ocr", text, "image", .75)] if text else []
        if mime.startswith("audio/") or "audio" in kind or "voice" in kind:
            text = self._transcribe(path)
            return [_item("transcription", text, "audio", .7)] if text else []
        if mime.startswith("video/") or "video" in kind:
            return self._video(path)
        return []

    def _ocr(self, path):
        executable = shutil.which("tesseract")
        if not executable:
            return ""
        result = subprocess.run(
            [executable, str(path), "stdout"], capture_output=True, text=True,
            timeout=self.timeout, check=False,
        )
        return _bounded(result.stdout)

    def _transcribe(self, path):
        executable = shutil.which("whisper")
        if not executable or not self.whisper_model or not self.whisper_model.is_file():
            return ""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [executable, str(path), "--model", str(self.whisper_model),
                 "--device", "cpu",
                 "--output_format", "json", "--output_dir", directory],
                capture_output=True, text=True, timeout=self.timeout, check=False,
            )
            if result.returncode:
                return ""
            outputs = list(Path(directory).glob("*.json"))
            if not outputs:
                return ""
            try:
                return _bounded(json.loads(outputs[0].read_text()).get("text"))
            except (OSError, ValueError, TypeError):
                return ""

    def _video(self, path):
        executable = shutil.which("ffmpeg")
        if not executable:
            return []
        derived = []
        with tempfile.TemporaryDirectory() as directory:
            pattern = str(Path(directory) / "frame-%02d.png")
            subprocess.run(
                [executable, "-v", "error", "-i", str(path), "-vf", "fps=1/30",
                 "-frames:v", "3", pattern], capture_output=True,
                timeout=self.timeout, check=False,
            )
            for index, frame in enumerate(sorted(Path(directory).glob("frame-*.png"))):
                text = self._ocr(frame)
                if text:
                    derived.append(_item(
                        "keyframe-ocr", text, f"keyframe:{index}", .65
                    ))
        transcript = self._transcribe(path)
        if transcript:
            derived.append(_item("transcription", transcript, "video-audio", .65))
        return derived


class PublicMediaDerivationEngine:
    def __init__(self, store, media_directory, processor=None, enabled=False,
                 batch_size=5, timeout=45, whisper_model=None,
                 retention_hours=168):
        self.store = store
        self.media_directory = Path(media_directory).resolve()
        self.processor = processor or LocalMediaProcessor(
            timeout=timeout, whisper_model=whisper_model
        )
        self.enabled = bool(enabled)
        self.batch_size = max(1, min(25, int(batch_size)))
        self.retention_hours = max(1, min(8760, int(retention_hours)))

    def run_batch(self):
        if not self.enabled:
            return MediaDerivationResult()
        now = utc_now()
        with self.store._connect() as connection:
            self._state(connection, now)
            rows = connection.execute(
                """SELECT versions.id version_id,versions.document_id,
                          versions.content_hash input_hash,
                          versions.metadata version_metadata
                   FROM document_versions versions
                   WHERE json_extract(versions.metadata,'$.media_downloaded')=1
                     AND NOT EXISTS (
                       SELECT 1 FROM public_media_derivations derivation
                       WHERE derivation.document_version_id=versions.id
                         AND derivation.method=?
                     )
                   ORDER BY versions.id LIMIT ?""",
                (METHOD, self.batch_size),
            ).fetchall()
        completed = unavailable = failed = 0
        for raw in rows:
            row = dict(raw)
            metadata = self.store._json_load(row["version_metadata"], {})
            status = self._derive(row, metadata, now)
            completed += status == "complete"
            unavailable += status == "unavailable"
            failed += status == "failed"
        with self.store._connect() as connection:
            connection.execute(
                """UPDATE public_media_derivation_state SET
                     cursor_version_id=MAX(cursor_version_id,?),
                     processed=processed+?,completed=completed+?,
                     unavailable=unavailable+?,failed=failed+?,updated_at=?
                   WHERE lane=?""",
                (max([int(row["version_id"]) for row in rows], default=0),
                 len(rows), completed, unavailable, failed, now, LANE),
            )
        self._expire_raw_media()
        return MediaDerivationResult(len(rows), completed, unavailable, failed)

    def _derive(self, row, metadata, now):
        media_hash = str(metadata.get("media_sha256") or "")
        path = self._safe_path(metadata.get("media_local_path"))
        if not path or not path.is_file() or not media_hash:
            self._record(row, metadata, media_hash, "unavailable", "", 0,
                         "", "media-unavailable", now)
            return "unavailable"
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest() != media_hash:
                self._record(row, metadata, media_hash, "failed", "", 0,
                             "", "hash-mismatch", now)
                return "failed"
            outputs = self.processor.derive(
                path, metadata.get("media_mime_type"), metadata.get("media_type")
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            self._record(row, metadata, media_hash, "failed", "", 0,
                         "", "processor-failed", now)
            return "failed"
        if not outputs:
            self._record(row, metadata, media_hash, "unavailable", "", 0,
                         "", "processor-unavailable", now)
            return "unavailable"
        for output in outputs[:10]:
            self._record(
                row, metadata, media_hash, "complete",
                _bounded(output.get("text")), output.get("confidence", 0),
                output.get("locator", ""), "", now,
                kind=output.get("kind", "derived-text"),
            )
        with self.store._connect() as connection:
            connection.execute(
                """UPDATE document_enrichments SET status='media-derived-pending',
                          updated_at=? WHERE document_version_id=?""",
                (now, row["version_id"]),
            )
        return "complete"

    def _record(self, row, metadata, media_hash, status, text, confidence,
                locator, error, now, kind="media-status"):
        with self.store._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO public_media_derivations (
                     document_id,document_version_id,input_hash,media_hash,
                     media_type,mime_type,byte_size,derivation_kind,derived_text,
                     confidence,evidence_locator,status,provider,model,method,
                     error_code,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["document_id"], row["version_id"], row["input_hash"],
                 media_hash, str(metadata.get("media_type") or ""),
                 str(metadata.get("media_mime_type") or ""),
                 int(metadata.get("media_size_bytes") or 0), str(kind), text,
                 max(0, min(.95, float(confidence or 0))), str(locator)[:200],
                 status, type(self.processor).__name__, "", METHOD, error,
                 now, now),
            )

    def _safe_path(self, value):
        if not value:
            return None
        try:
            path = Path(value).resolve()
            path.relative_to(self.media_directory)
            return path
        except (OSError, ValueError):
            return None

    def _expire_raw_media(self):
        if not self.media_directory.is_dir():
            return
        cutoff = time.time() - self.retention_hours * 3600
        for path in self.media_directory.iterdir():
            if not re.fullmatch(r"[0-9a-f]{64}", path.name):
                continue
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    def _state(self, connection, now):
        connection.execute(
            """INSERT OR IGNORE INTO public_media_derivation_state
                 (lane,started_at,updated_at) VALUES (?,?,?)""",
            (LANE, now, now),
        )


def _item(kind, text, locator, confidence):
    return {"kind": kind, "text": text, "locator": locator,
            "confidence": confidence}


def _bounded(value, limit=20_000):
    return " ".join(str(value or "").split())[:limit]
