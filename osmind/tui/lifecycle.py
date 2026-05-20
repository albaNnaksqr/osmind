from __future__ import annotations

import hashlib
import json


def resources_hash(resources: dict | None) -> str:
    if not resources:
        return ""
    payload = json.dumps(resources, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
