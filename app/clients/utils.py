from typing import Any


def get_by_path(payload: Any, path: str, default: Any = None) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return default
            continue
        if not isinstance(current, dict):
            return default
        if part not in current:
            return default
        current = current[part]
    return current

