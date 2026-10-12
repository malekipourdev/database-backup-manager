"""Run the agent: python -m mbp.agent"""

import logging

import uvicorn

from mbp.agent.app import AgentSettings, create_agent_app
from mbp.agent.tls import ensure_certificate
from mbp.logging import configure_logging, register_secret
from mbp.security.agent_auth import fingerprint

logger = logging.getLogger("mbp.agent")


def main() -> None:
    configure_logging()
    # httpx logs every Docker API request at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = AgentSettings()  # type: ignore[call-arg]
    register_secret(settings.token())
    tls: dict = {}
    cert_fp = ""
    if settings.remote:
        cert, key, der = ensure_certificate(settings.agent_data_dir)
        cert_fp = fingerprint(der)
        tls = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        logger.info("Remote mode: HTTPS, certificate fingerprint %s", cert_fp)
    app = create_agent_app(settings, cert_fingerprint=cert_fp)
    uvicorn.run(app, host=settings.agent_bind, port=settings.agent_port, access_log=False, **tls)


if __name__ == "__main__":
    main()
