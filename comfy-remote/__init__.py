"""Comfy Remote: a phone-friendly control page served by ComfyUI itself.

Open http://<PC-IP>:8188/remote on your phone.
API-format workflows live in ./workflows/*.json.
"""
import json
import os
import re

from aiohttp import web
from server import PromptServer

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(HERE, "workflows")
NAME_RE = re.compile(r"^[\w .()-]{1,80}$")
os.makedirs(WF_DIR, exist_ok=True)

routes = PromptServer.instance.routes


def _is_api_workflow(data):
    return (
        isinstance(data, dict)
        and len(data) > 0
        and all(isinstance(v, dict) and "class_type" in v for v in data.values())
    )


@routes.get("/remote")
async def remote_page(request):
    return web.FileResponse(os.path.join(HERE, "remote.html"))


@routes.get("/remote/workflows")
async def list_workflows(request):
    names = sorted(f[:-5] for f in os.listdir(WF_DIR) if f.lower().endswith(".json"))
    return web.json_response(names)


@routes.get("/remote/workflows/{name}")
async def get_workflow(request):
    name = request.match_info["name"]
    path = os.path.join(WF_DIR, name + ".json")
    if not NAME_RE.match(name) or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path)


@routes.post("/remote/workflows/{name}")
async def save_workflow(request):
    name = request.match_info["name"]
    if not NAME_RE.match(name):
        raise web.HTTPBadRequest(text="Invalid name")
    data = await request.json()
    if not _is_api_workflow(data):
        raise web.HTTPBadRequest(text="Not an API-format workflow (use Export (API) in ComfyUI)")
    with open(os.path.join(WF_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return web.json_response({"ok": True})


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
