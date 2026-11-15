"""Offline bundle health: never creates posts, subscriptions or network traffic."""

import json


def health_result() -> dict:
    import flowsteward_extension_sdk
    import PIL
    import twitter_text

    return {
        "ok": bool(PIL and twitter_text and flowsteward_extension_sdk),
        "result": {"status": "bundle_ready", "provider_connection_checked": False},
    }


if __name__ == "__main__":
    print(json.dumps(health_result()))
