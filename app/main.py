from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.ai import build_interpreter
from app.config import get_settings
from app.db import Database
from app.domain import ActionExecutor
from app.models import ChatRequest, ChatResponse, Item, ItemPatch
from app.monitor import Monitor
from app.repository import Repository


settings = get_settings()
db = Database(settings.database_path)
repository = Repository(db)
interpreter = build_interpreter(
    settings.ai_provider,
    settings.openai_api_key,
    settings.openai_model,
    settings.ai_input_price_per_million,
    settings.ai_cached_input_price_per_million,
    settings.ai_output_price_per_million,
)
executor = ActionExecutor(repository)
monitor = Monitor(repository, settings.timezone)


async def monitor_loop() -> None:
    while True:
        try:
            monitor.run()
        except Exception as exc:
            print(f"Monitor error: {exc}")
        await asyncio.sleep(settings.monitor_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.initialize()
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Compagno di viaggio AI", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/data", include_in_schema=False)
async def data_view() -> FileResponse:
    return FileResponse(static_dir / "data.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest() -> FileResponse:
    return FileResponse(static_dir / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    return FileResponse(
        static_dir / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Service-Worker-Allowed": "/"},
    )


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "ai_provider": settings.ai_provider}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if settings.ai_provider == "openai" and repository.ai_usage_summary(settings.ai_monthly_budget_usd)["blocked"]:
        raise HTTPException(status_code=402, detail="Budget AI mensile raggiunto. Nessuna chiamata è stata effettuata.")
    message = request.message.strip()
    user_message_id = repository.add_message("user", message)
    try:
        result = await interpreter.interpret(message, repository.list_items(), repository.recent_messages())
        if result.provider_usage:
            repository.record_ai_usage(result.provider_usage)
        changed = executor.execute(result.actions, user_message_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Provider AI non disponibile: {exc}") from exc
    repository.add_message("assistant", result.reply, {"actions": [action.model_dump(mode="json") for action in result.actions]})
    return ChatResponse(reply=result.reply, actions=result.actions, changed_items=changed)


@app.get("/api/messages")
async def messages(limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return repository.recent_messages(limit)


@app.get("/api/items", response_model=list[Item])
async def items(status: list[str] | None = Query(None)) -> list[Item]:
    return repository.list_items(status)


@app.patch("/api/items/{item_id}", response_model=Item)
async def patch_item(item_id: str, patch: ItemPatch) -> Item:
    try:
        return repository.update_item(item_id, patch.model_dump(exclude_unset=True, mode="json"), "manual", None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Elemento non trovato") from exc


@app.delete("/api/items/{item_id}", status_code=204, response_class=Response)
async def delete_item(item_id: str) -> Response:
    try:
        repository.delete_item(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Elemento non trovato") from exc
    return Response(status_code=204)


@app.get("/api/relations")
async def relations() -> list[dict]:
    return repository.list_relations()


@app.get("/api/activities")
async def activities(item_id: str | None = None) -> list[dict]:
    return repository.list_activity_records(item_id)


@app.get("/api/checkins")
async def checkins() -> list[dict]:
    return repository.pending_checkins()


@app.post("/api/checkins/run")
async def run_checkins() -> dict[str, list[dict]]:
    return {"created": monitor.run()}


@app.post("/api/checkins/{checkin_id}/deliver")
async def deliver_checkin(checkin_id: str) -> dict[str, str]:
    repository.deliver_checkin(checkin_id)
    return {"status": "delivered"}


@app.get("/api/audit")
async def audit(limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return repository.audit_log(limit)


@app.get("/api/usage")
async def usage() -> dict:
    return repository.ai_usage_summary(settings.ai_monthly_budget_usd)


@app.get("/api/debug/raw", include_in_schema=False)
async def raw_database() -> dict:
    return repository.raw_snapshot()
