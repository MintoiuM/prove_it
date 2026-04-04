from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class FileCache:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.base_dir / f"{digest}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        target = self._path_for_key(key)
        if not target.exists():
            return None
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def set(self, key: str, payload: dict[str, Any]) -> None:
        target = self._path_for_key(key)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle)


def make_cache_key(endpoint: str, params: dict[str, Any]) -> str:
    canonical_params = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return f"{endpoint}|{canonical_params}"

