"""Background manifest writer — checkpoint saves never block task completion."""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from capability.gcs_checkpoint import upload_manifest
from capability.manifest import write_manifest


class ManifestWriter:
    def __init__(
        self,
        path: Path,
        *,
        stage: str,
        model: str,
        max_actions: int,
        runs: list[dict],
        lock: threading.Lock,
        gcs_checkpoint: bool = True,
    ) -> None:
        self._path = path
        self._stage = stage
        self._model = model
        self._max_actions = max_actions
        self._runs = runs
        self._lock = lock
        self._gcs_checkpoint = gcs_checkpoint
        self._queue: queue.Queue[bool | None] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="manifest-writer", daemon=True)
        self._thread.start()

    def request_save(self) -> None:
        self._queue.put(True)

    def flush(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=120)

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._do_save()
                break
            self._do_save()

    def _do_save(self) -> None:
        with self._lock:
            snapshot = list(self._runs)
        try:
            write_manifest(
                self._path,
                snapshot,
                stage=self._stage,
                model=self._model,
                max_actions=self._max_actions,
                slim=True,
            )
        except OSError as exc:
            print(f"WARN manifest save failed: {exc}", flush=True)
            return
        if self._gcs_checkpoint:
            try:
                upload_manifest(self._path)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN gcs manifest checkpoint failed: {exc}", flush=True)
