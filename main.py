"""Single-request, bounded JSON subprocess entrypoint."""

from __future__ import annotations

import json
import sys

from x_extension.runtime import dispatch, failure


def main() -> int:
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    try:
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("large envelope")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("object required")
        response = dispatch(payload)
    except (ValueError, UnicodeDecodeError):
        response = failure("invalid_payload", "A bounded JSON object request is required.")
    encoded = json.dumps(response, allow_nan=False, ensure_ascii=True)
    if len(encoded) > 1024 * 1024:
        response = failure("response_too_large", "X extension response exceeds the safe limit.")
        encoded = json.dumps(response)
    print(encoded)
    return 0 if response["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
