"""Care Finder API.

    uvicorn app.main:app --reload --port 8000        (from backend/)

    GET  /api/health
    GET  /api/services                  the 16 services and their travel distances
    GET  /api/locations?q=Darbhanga     location candidates (for autocomplete / disambiguation)
    POST /api/recommend                 {service, location, urgency, weights, broadcast_to_ui}
    GET  /api/last                      the most recent broadcast (polling fallback for the UI)
    WS   /ws/live                       pushes every broadcast recommendation to the UI
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


@app.get("/api/locations")
def locations(q: str):
    return engine.resolve_location(get_store(), q)[:10]


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
        await live.broadcast({"type": "recommendation", "source": req.source, "audience": req.audience, "payload": resp})
    return JSONResponse(resp)


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
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
