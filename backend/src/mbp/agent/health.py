"""The container's health check: python -m mbp.agent.health"""

import ssl
import sys
import urllib.request

from mbp.agent.app import AgentSettings


def main() -> int:
    settings = AgentSettings()  # type: ignore[call-arg]
    scheme = "https" if settings.remote else "http"
    context = None
    if settings.remote:
        # Only whether it answers; the panel is what verifies the certificate.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    url = f"{scheme}://127.0.0.1:{settings.agent_port}/health"
    try:
        urllib.request.urlopen(url, timeout=4, context=context)  # noqa: S310 - fixed URL
    except OSError:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
