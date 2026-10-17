from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import DEFAULT_MODEL, UPLOAD_DIR, chat_models, load_models
from .documents import delete_doc, docs_context, get_session, image_content_parts, save_upload
from .llm import build_messages, model_meta, retrieve_catalog, stream_chat
from .trials_db import catalog_stats

ROOT: Path = Path(__file__).resolve().parent.parent
STATIC: Path = ROOT / "static"

app: FastAPI = FastAPI(title="Avicenna Rakathon Chat", version="0.1.0")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class ChatRequest(BaseModel):
    message: str = Field(default="")
    model: str = Field(default=DEFAULT_MODEL)
    session_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    language: Literal["cs", "en"] = "cs"


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "catalog": catalog_stats()}


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    all_models: list[dict[str, Any]] = load_models()
    chats: list[dict[str, Any]] = chat_models(multimodal_first=True)
    return {
        "default": DEFAULT_MODEL,
        "chat": chats,
        "all": all_models,
    }


@app.post("/api/upload")
async def upload(
    session_id: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    session = get_session(session_id)
    data: bytes = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 25 MB)")
    doc = save_upload(session, file.filename or "upload.bin", data)
    return {
        "session_id": session.session_id,
        "doc": {
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "kind": doc.kind,
            "media_type": doc.media_type,
            "chars": len(doc.text),
            "error": doc.error,
        },
        "docs": _doc_list(session),
    }


def _doc_list(session: Any) -> list[dict[str, Any]]:
    return [
        {"doc_id": d.doc_id, "filename": d.filename, "kind": d.kind, "chars": len(d.text), "error": d.error}
        for d in session.docs
    ]


@app.get("/api/session/{session_id}/docs")
def session_docs(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    return {
        "session_id": session.session_id,
        "docs": _doc_list(session),
    }


@app.delete("/api/session/{session_id}/docs/{doc_id}")
def remove_doc(session_id: str, doc_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not delete_doc(session, doc_id):
        raise HTTPException(404, "Document not found")
    return {"session_id": session.session_id, "docs": _doc_list(session)}


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    try:
        meta: dict[str, Any] = model_meta(req.model)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc

    if meta.get("kind") == "image":
        raise HTTPException(400, "Image-generation models are not supported in chat")

    session = get_session(req.session_id)
    multimodal: bool = bool(meta.get("multimodal"))
    images = image_content_parts(session) if multimodal else []
    if images and not multimodal:
        raise HTTPException(400, "Selected model is not multimodal; remove images or switch model")

    user_text: str = req.message.strip()
    catalog_blob: str = retrieve_catalog(user_text) if user_text else retrieve_catalog("Motol Prague recruiting")
    messages = build_messages(
        user_text=user_text,
        history=req.history,
        doc_context=docs_context(session),
        image_parts=images,
        multimodal=multimodal,
        catalog_blob=catalog_blob,
        language=req.language,
    )
    if not user_text and not images and not session.docs:
        raise HTTPException(400, "Empty message and no documents")

    async def event_stream() -> Any:
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session.session_id, 'model': req.model})}\n\n"
        try:
            async for token in stream_chat(req.model, messages):
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
