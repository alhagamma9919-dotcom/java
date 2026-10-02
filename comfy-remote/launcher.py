"""Comfy Remote launcher.

Small always-on server for the PC. From a phone (home Wi-Fi or Tailscale) it lets you
start/stop ComfyUI and use a mobile UI for your workflows.

- ComfyUI itself only listens on 127.0.0.1; the phone reaches it through /comfy/* here.
- Every request needs the PIN cookie and must come from a private/Tailscale address.

Run with ComfyUI's own Python (it already has aiohttp):
    C:\\ComfyUI\\venv\\Scripts\\python.exe launcher.py
"""
import asyncio
import hmac
import ipaddress
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
from aiohttp import web

HERE = Path(__file__).resolve().parent
CFG_PATH = HERE / "config.json"
WF_DIR = HERE / "workflows"
LOG_PATH = HERE / "comfyui.log"
NAME_RE = re.compile(r"^[\w .()-]{1,80}$")
WINDOWS = os.name == "nt"
COOKIE = "cr_session"

ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128",                            # this PC
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",     # home network
    "100.64.0.0/10", "fd7a:115c:a1e0::/48",              # Tailscale
)]

DEFAULTS = {
    "listen": "0.0.0.0",
    "port": 8190,
    "comfy_dir": r"C:\ComfyUI",
    "comfy_python": "",
    "comfy_port": 8188,
    "comfy_args": ["--preview-method", "auto"],
    "pin": "",
    "comfy_api_key": "",
    "autostart_comfy": False,
}


def load_cfg():
    cfg = dict(DEFAULTS)
    if CFG_PATH.exists():
        cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8-sig")))
    changed = False
    if not cfg.get("pin"):
        cfg["pin"] = f"{secrets.randbelow(10**6):06d}"
        changed = True
    if not cfg.get("session_secret"):
        cfg["session_secret"] = secrets.token_urlsafe(32)
        changed = True
    if changed:
        CFG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


CFG = load_cfg()
COMFY = f"http://127.0.0.1:{CFG['comfy_port']}"


def comfy_python():
    if CFG["comfy_python"]:
        return CFG["comfy_python"]
    d = Path(CFG["comfy_dir"])
    for p in (d / "venv" / "Scripts" / "python.exe", d / "venv" / "bin" / "python",
              d.parent / "python_embeded" / "python.exe"):
        if p.exists():
            return str(p)
    return sys.executable


# ---------------------------------------------------------------- ComfyUI process
class Comfy:
    proc = None
    started = 0.0

    @staticmethod
    def pid_on_port():
        """PID listening on the ComfyUI port (also finds a ComfyUI started by hand)."""
        try:
            if WINDOWS:
                out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW).stdout
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{CFG['comfy_port']}"):
                        return int(parts[4])
            else:
                out = subprocess.run(["lsof", "-t", f"-iTCP:{CFG['comfy_port']}", "-sTCP:LISTEN"],
                                     capture_output=True, text=True).stdout.split()
                return int(out[0]) if out else None
        except Exception:
            return None
        return None

    @classmethod
    def alive(cls):
        return cls.proc is not None and cls.proc.poll() is None

    @classmethod
    def start(cls):
        if cls.alive() or cls.pid_on_port():
            return "already running"
        main = Path(CFG["comfy_dir"]) / "main.py"
        if not main.exists():
            raise web.HTTPBadRequest(text=f"main.py not found in {CFG['comfy_dir']} (fix comfy_dir in config.json)")
        cmd = [comfy_python(), "main.py", "--listen", "127.0.0.1", "--port", str(CFG["comfy_port"]), *CFG["comfy_args"]]
        log = open(LOG_PATH, "ab")
        log.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')}: {' '.join(cmd)}\n".encode())
        log.flush()
        cls.proc = subprocess.Popen(
            cmd, cwd=CFG["comfy_dir"], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0,
        )
        cls.started = time.time()
        return "starting"

    @classmethod
    def stop(cls):
        pids = {p for p in (cls.proc.pid if cls.alive() else None, cls.pid_on_port()) if p}
        for pid in pids:
            try:
                if WINDOWS:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        cls.proc = None
        return "stopped" if pids else "not running"


_gpu_cache = {"t": 0, "v": None}


def gpu_stats():
    if time.time() - _gpu_cache["t"] < 2:
        return _gpu_cache["v"]
    v = None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0).stdout.strip().splitlines()
        if out:
            name, util, used, total, temp = [x.strip() for x in out[0].split(",")]
            v = {"name": name, "util": int(util), "mem_used": int(used), "mem_total": int(total), "temp": int(temp)}
    except Exception:
        pass
    _gpu_cache.update(t=time.time(), v=v)
    return v


def ram_stats():
    """System RAM and commit (RAM + page file) in GB."""
    try:
        if WINDOWS:
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            m = MemStatus()
            m.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            total, avail = m.ullTotalPhys, m.ullAvailPhys
            c_total, c_avail = m.ullTotalPageFile, m.ullAvailPageFile
        else:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    info[k] = int(v.split()[0]) * 1024
            total, avail = info["MemTotal"], info["MemAvailable"]
            c_total = total + info.get("SwapTotal", 0)
            c_avail = avail + info.get("SwapFree", 0)
        gb = lambda x: round(x / 2**30, 1)
        return {"used": gb(total - avail), "total": gb(total),
                "commit_used": gb(c_total - c_avail), "commit_total": gb(c_total)}
    except Exception:
        return None


# ---------------------------------------------------------------- security
_fails = {}


def client_ip(request):
    try:
        ip = ipaddress.ip_address(request.remote)
        return getattr(ip, "ipv4_mapped", None) or ip
    except (TypeError, ValueError):
        return None


@web.middleware
async def guard(request, handler):
    ip = client_ip(request)
    if ip is None or not any(ip in n for n in ALLOWED_NETS):
        raise web.HTTPForbidden(text="Only home network / Tailscale allowed")
    if request.path in ("/", "/api/login"):
        return await handler(request)
    if not hmac.compare_digest(request.cookies.get(COOKIE, ""), CFG["session_secret"]):
        raise web.HTTPUnauthorized(text="Login required")
    return await handler(request)


async def login(request):
    ip = str(client_ip(request))
    fails, until = _fails.get(ip, (0, 0))
    if until > time.time():
        raise web.HTTPTooManyRequests(text=f"Too many tries, wait {int(until - time.time())}s")
    pin = str((await request.json()).get("pin", ""))
    if not hmac.compare_digest(pin, str(CFG["pin"])):
        fails += 1
        _fails[ip] = (fails, time.time() + 600 if fails >= 5 else 0)
        await asyncio.sleep(1)
        raise web.HTTPUnauthorized(text="Wrong PIN")
    _fails.pop(ip, None)
    resp = web.json_response({"ok": True})
    resp.set_cookie(COOKIE, CFG["session_secret"], max_age=365 * 86400, httponly=True, samesite="Strict")
    return resp


# ---------------------------------------------------------------- API
async def index(request):
    return web.FileResponse(HERE / "index.html", headers={"Cache-Control": "no-cache"})


async def comfy_up(session):
    try:
        async with session.get(COMFY + "/system_stats", timeout=aiohttp.ClientTimeout(total=1.5)) as r:
            return r.status == 200
    except Exception:
        return False


async def status(request):
    up = await comfy_up(request.app["session"])
    if up:
        state = "running"
    elif Comfy.alive():
        state = "starting"
    else:
        state = "stopped"
    exit_code = Comfy.proc.returncode if Comfy.proc is not None and not Comfy.alive() else None
    gpu = await asyncio.get_running_loop().run_in_executor(None, gpu_stats)
    return web.json_response({
        "state": state,
        "managed": Comfy.alive(),
        "uptime": int(time.time() - Comfy.started) if Comfy.alive() else None,
        "exit_code": exit_code,
        "gpu": gpu,
        "ram": ram_stats(),
        "api_key": bool(CFG.get("comfy_api_key")),
    })


async def start(request):
    return web.json_response({"result": Comfy.start()})


async def stop(request):
    return web.json_response({"result": await asyncio.get_running_loop().run_in_executor(None, Comfy.stop)})


async def restart(request):
    await asyncio.get_running_loop().run_in_executor(None, Comfy.stop)
    await asyncio.sleep(2)
    return web.json_response({"result": Comfy.start()})


async def log_tail(request):
    n = min(int(request.query.get("lines", 200)), 2000)
    if not LOG_PATH.exists():
        return web.Response(text="(no log yet)")
    with open(LOG_PATH, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 256 * 1024))
        lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
    return web.Response(text="\n".join(lines))


def _wf_path(name):
    if not NAME_RE.match(name):
        raise web.HTTPBadRequest(text="Invalid name")
    return WF_DIR / f"{name}.json"


def _is_api_workflow(data):
    return (isinstance(data, dict) and len(data) > 0
            and all(isinstance(v, dict) and "class_type" in v for v in data.values()))


async def wf_list(request):
    return web.json_response(sorted(p.stem for p in WF_DIR.glob("*.json") if not p.stem.endswith(".ui")))


async def wf_get(request):
    p = _wf_path(request.match_info["name"])
    if not p.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(p)


async def wf_ui(request):
    """Optional <name>.ui.json: curated labels/groups for the phone form."""
    p = _wf_path(request.match_info["name"] + ".ui")
    return web.FileResponse(p) if p.exists() else web.json_response({})


async def wf_save(request):
    p = _wf_path(request.match_info["name"])
    data = await request.json()
    if not _is_api_workflow(data):
        raise web.HTTPBadRequest(text="Not an API-format workflow (ComfyUI: Workflow → Export (API))")
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return web.json_response({"ok": True})


async def wf_delete(request):
    for p in (_wf_path(request.match_info["name"]), _wf_path(request.match_info["name"] + ".ui")):
        if p.exists():
            p.unlink()
    return web.json_response({"ok": True})


# ---------------------------------------------------------------- input / output files
FILE_DIRS = ("input", "output")


def _files_root(kind):
    if kind not in FILE_DIRS:
        raise web.HTTPBadRequest(text="dir must be input or output")
    return (Path(CFG["comfy_dir"]) / kind).resolve()


def _list_files(root):
    out = []
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                out.append({"path": p.relative_to(root).as_posix(), "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda x: -x["mtime"])
    return out


def _safe_file(root, rel):
    """Only files inside ComfyUI's input/output folder; no '..' tricks."""
    p = (root / rel).resolve()
    if root not in p.parents or not p.is_file():
        raise web.HTTPBadRequest(text=f"Invalid file: {rel}")
    return p


async def files_list(request):
    kind = request.query.get("dir", "")
    files = await asyncio.get_running_loop().run_in_executor(None, _list_files, _files_root(kind))
    return web.json_response({"dir": kind, "count": len(files), "bytes": sum(f["size"] for f in files), "files": files[:1000]})


async def files_delete(request):
    body = await request.json()
    root = _files_root(body.get("dir", ""))

    def work():
        if body.get("all"):
            targets = [root / f["path"] for f in _list_files(root)]
        else:
            targets = [_safe_file(root, rel) for rel in body.get("paths", [])[:5000]]
        n = freed = 0
        for p in targets:
            try:
                size = p.stat().st_size
                p.unlink()
                n += 1
                freed += size
            except OSError:
                pass
        return n, freed

    n, freed = await asyncio.get_running_loop().run_in_executor(None, work)
    return web.json_response({"deleted": n, "freed": freed})


# ---------------------------------------------------------------- ComfyUI proxy
HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "upgrade"}


async def proxy(request):
    tail = request.match_info["tail"]
    session = request.app["session"]
    if tail == "ws":
        return await ws_proxy(request, session)
    body = await request.read()
    if request.method == "POST" and tail == "prompt" and CFG.get("comfy_api_key"):
        j = json.loads(body)
        j.setdefault("extra_data", {})["api_key_comfy_org"] = CFG["comfy_api_key"]  # for API nodes (MiniMax etc.)
        body = json.dumps(j).encode()
    headers = {k: v for k, v in request.headers.items() if k.lower() in ("content-type", "accept", "range")}
    try:
        async with session.request(request.method, f"{COMFY}/{tail}", params=request.query,
                                   data=body or None, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=600)) as r:
            resp = web.StreamResponse(status=r.status, headers={
                k: v for k, v in r.headers.items() if k.lower() not in HOP and k.lower() != "set-cookie"})
            await resp.prepare(request)
            async for chunk in r.content.iter_chunked(64 * 1024):
                await resp.write(chunk)
            await resp.write_eof()
            return resp
    except aiohttp.ClientConnectorError:
        raise web.HTTPServiceUnavailable(text="ComfyUI is not running")


async def ws_proxy(request, session):
    down = web.WebSocketResponse(max_msg_size=0, heartbeat=30)
    await down.prepare(request)
    try:
        async with session.ws_connect(f"{COMFY.replace('http', 'ws', 1)}/ws", params=request.query,
                                      max_msg_size=0) as up:
            async def up_to_down():
                async for m in up:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        await down.send_str(m.data)
                    elif m.type == aiohttp.WSMsgType.BINARY:
                        await down.send_bytes(m.data)
                    else:
                        break

            async def down_to_up():
                async for m in down:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        await up.send_str(m.data)
                    elif m.type != aiohttp.WSMsgType.BINARY:
                        break

            tasks = [asyncio.ensure_future(up_to_down()), asyncio.ensure_future(down_to_up())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception:
        pass
    await down.close()
    return down


# ---------------------------------------------------------------- app
async def on_startup(app):
    app["session"] = aiohttp.ClientSession()
    if CFG.get("autostart_comfy"):
        try:
            Comfy.start()          # warm up at boot, so it is ready when you open the phone
        except Exception:
            pass


async def on_cleanup(app):
    await app["session"].close()


def make_app():
    WF_DIR.mkdir(exist_ok=True)
    app = web.Application(middlewares=[guard], client_max_size=200 * 1024 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.add_routes([
        web.get("/", index),
        web.post("/api/login", login),
        web.get("/api/status", status),
        web.post("/api/start", start),
        web.post("/api/stop", stop),
        web.post("/api/restart", restart),
        web.get("/api/log", log_tail),
        web.get("/api/workflows", wf_list),
        web.get("/api/workflows/{name}", wf_get),
        web.get("/api/workflows/{name}/ui", wf_ui),
        web.post("/api/workflows/{name}", wf_save),
        web.delete("/api/workflows/{name}", wf_delete),
        web.get("/api/files", files_list),
        web.post("/api/files/delete", files_delete),
        web.route("*", "/comfy/{tail:.*}", proxy),
    ])
    return app


if __name__ == "__main__":
    print(f"Comfy Remote on http://{CFG['listen']}:{CFG['port']}  (PIN is in {CFG_PATH})")
    web.run_app(make_app(), host=CFG["listen"], port=CFG["port"], print=None)
