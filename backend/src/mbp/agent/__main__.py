"""Run the agent: python -m mbp.agent"""

import logging

import uvicorn

from mbp.agent.app import AgentSettings, create_agent_app
from mbp.logging import configure_logging


def main() -> None:
    configure_logging()
    # httpx logs every Docker API request at INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = AgentSettings()  # type: ignore[call-arg]
    app = create_agent_app(settings)
    uvicorn.run(app, host=settings.agent_bind, port=settings.agent_port, access_log=False)


if __name__ == "__main__":
    main()
