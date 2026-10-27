"""Web servers on a server (nginx, Apache): the sites they serve. Read-only for now."""

from fastapi import APIRouter, Depends, Request

from mbp.api.containers import get_server
from mbp.api.schemas import WebServerList
from mbp.models import Server

router = APIRouter(tags=["webservers"])


@router.get("/webservers", response_model=WebServerList)
def list_webservers(request: Request, server: Server = Depends(get_server)) -> dict:
    return request.app.state.agents.for_server(server).webservers()
