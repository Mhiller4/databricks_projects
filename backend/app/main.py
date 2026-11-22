"""Care Finder API.

    uvicorn app.main:app --reload --port 8000        (from backend/)

    GET  /api/health
    GET  /api/config                   phone banner, services, funnel base, voice availability
    GET  /api/services                  the 16 services and their travel distances
    GET  /api/locations?q=Ban           type-ahead for the location box (from 2 characters)
    POST /api/recommend                 {service, location, urgency, weights, broadcast_to_ui, session}
    POST /api/livekit/token             short-lived token for a web voice session (role as attribute)
    GET  /api/last                      the most recent broadcast (polling fallback for the UI)
    WS   /ws/live                       pushes every broadcast recommendation to the UI
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from livekit import api

from . import engine
from .data import get_store


class LatLon(BaseModel):
    lat: float
    lon: float


class Weights(BaseModel):
    proximity: float | None = None
    evidence: float | None = None
    trust: float | None = None
    depth: float | None = None


class RecommendRequest(BaseModel):
    service: str = Field(..., examples=["dialysis"])
    location: str | LatLon = Field(..., examples=["Darbhanga, Bihar"])
    urgency: Literal["routine", "emergency"] = "routine"
    weights: Weights | None = None
    top_n: int = Field(3, ge=1, le=3)
    broadcast_to_ui: bool = False
    source: str = Field("ui", description="who asked: ui | voice")
    audience: Literal["provider", "patient"] | None = Field(None, description="tailors the spoken summary")
    session: str | None = Field(None, description="LiveKit room name; tags broadcasts so /monitor can group them")


class TokenRequest(BaseModel):
    role: Literal["provider", "patient"] | None = None
    language: str | None = None


class TokenLimiter:
    """Small in-memory sliding window so the public page can't drain the free LiveKit/Gemini quotas."""

    def __init__(self, max_events: int = 10, window_s: float = 60.0):
        self.max_events, self.window_s = max_events, window_s
        self.events: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self.events.setdefault(key, [])
        hits[:] = [t for t in hits if now - t < self.window_s]
        if len(hits) >= self.max_events:
            return False
        hits.append(now)
        return True

    def clear(self) -> None:
        self.events.clear()


class Live:
    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.last: dict | None = None

    async def broadcast(self, msg: dict):
        self.last = msg
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


live = Live()
token_limiter = TokenLimiter(max_events=10, window_s=60.0)


def _voice_configured() -> bool:
    return bool(os.environ.get("LIVEKIT_URL") and os.environ.get("LIVEKIT_API_KEY") and os.environ.get("LIVEKIT_API_SECRET"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_store()  # load Parquet into DuckDB once, at startup
    yield


app = FastAPI(title="Care Finder API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    s = get_store()
    return {"ok": True, "funnel_base": s.funnel_base}


@app.get("/api/services")
def services():
    return [{"key": s.key, "label": s.label, "tau_km": s.tau_km, "synonyms": list(s.synonyms), "note": s.note}
            for s in engine.care.SERVICES]


@app.get("/api/config")
def config():
    """Everything the page needs once at load: services, funnel base, phone banner, voice availability."""
    return {
        "phone_number": os.environ.get("CARE_FINDER_PHONE", ""),
        "services": services(),
        "funnel_base": get_store().funnel_base,
        "livekit_enabled": _voice_configured(),
    }


@app.get("/api/locations")
def locations(q: str, limit: int = engine.SUGGEST_LIMIT):
    """Type-ahead for the location box: prefix matches from two characters (8 by default, at most 40;
    the voice agent asks for more so it can narrow by district)."""
    return engine.location_suggest(get_store(), q, limit=max(1, min(int(limit), 40)))


@app.post("/api/recommend")
async def recommend(req: RecommendRequest):
    loc = req.location.model_dump() if isinstance(req.location, LatLon) else req.location
    weights = req.weights.model_dump() if req.weights else None
    try:
        resp = await asyncio.to_thread(
            engine.recommend, get_store(),
            engine.Request(service=req.service, location=loc, urgency=req.urgency, weights=weights, top_n=req.top_n, audience=req.audience),
        )
    except engine.CareFinderError as e:
        resp = {"status": e.status, "message": e.message, "spoken_summary": e.message, **e.extra,
                "query": {"service": req.service, "location": loc, "urgency": req.urgency}}
    if req.broadcast_to_ui:
        await live.broadcast({"type": "recommendation", "source": req.source, "audience": req.audience,
                              "session": req.session, "payload": resp})
    return JSONResponse(resp)


@app.post("/api/livekit/token")
def livekit_token(req: TokenRequest, request: Request):
    """A short-lived token for one web voice session (design 3.1).

    The role the user picked rides along as a participant attribute, so the agent skips the
    'press 1 / 2' greeter. Returns only the signed token and the room: never the API key.
    """
    if not _voice_configured():
        raise HTTPException(503, "voice is not configured on this server")
    client_ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "unknown"))
    client_ip = client_ip.split(",")[0].strip()
    if not token_limiter.allow(client_ip):
        raise HTTPException(429, "too many voice sessions from this address; wait a minute and try again")

    suffix = secrets.token_hex(4)  # 8 hex chars
    room_name, identity = f"web-{suffix}", f"web-user-{suffix}"
    attributes = {"care_finder.role": req.role or "", "care_finder.language": req.language or ""}
    token = (
        api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name("Web user")
        .with_attributes(attributes)
        .with_ttl(timedelta(minutes=15))
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True,
                                     can_subscribe=True, can_publish_data=True))
        .to_jwt()
    )
    return {"server_url": os.environ["LIVEKIT_URL"], "participant_token": token,
            "room_name": room_name, "identity": identity}


@app.get("/api/last")
def last():
    if live.last is None:
        raise HTTPException(404, "nothing broadcast yet")
    return live.last


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    live.clients.add(ws)
    try:
        if live.last:
            await ws.send_json(live.last)
        while True:
            await ws.receive_text()  # keep-alive; the UI may send pings
    except WebSocketDisconnect:
        live.clients.discard(ws)


# Serve the built React app (frontend/dist) at / when it exists
_HERE = Path(__file__).resolve()
# repo layout: <repo>/backend/app/main.py -> <repo>/frontend/dist ; assembled app: <app>/app/main.py -> <app>/frontend/dist
_DIST = next((p for p in (Path(os.environ.get("CARE_FINDER_STATIC", "")), _HERE.parents[2] / "frontend" / "dist",
                          _HERE.parents[1] / "frontend" / "dist") if str(p) not in ("", ".") and (p / "index.html").exists()),
             _HERE.parents[2] / "frontend" / "dist")
if not (_DIST / "index.html").exists():
    from fastapi.responses import RedirectResponse

    @app.get("/", include_in_schema=False)
    def root():  # no web page built yet: show the API docs
        return RedirectResponse("/docs")

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
