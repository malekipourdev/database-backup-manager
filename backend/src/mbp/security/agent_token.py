"""The shared secret between the backend and the Docker agent.

Derived from MBP_ENCRYPTION_KEY, which both containers already have, so the agent needs no
extra configuration. The agent can read any container's environment through docker.sock
anyway, so giving it the key adds no exposure.
"""

import hashlib
import hmac

PURPOSE = b"mbp-agent-v1"


def agent_token(encryption_key: str) -> str:
    first = encryption_key.split(",")[0].strip()
    if not first:
        raise RuntimeError("MBP_ENCRYPTION_KEY is missing or invalid")
    return hmac.new(first.encode("utf-8"), PURPOSE, hashlib.sha256).hexdigest()
