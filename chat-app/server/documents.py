from __future__ import annotations

import base64
import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .config import UPLOAD_DIR

TEXT_SUFFIXES: set[str] = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".log"}
DOCX_SUFFIXES: set[str] = {".docx"}
PDF_SUFFIXES: set[str] = {".pdf"}
IMAGE_SUFFIXES: set[str] = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_TEXT_CHARS: int = 120_000


@dataclass
class StoredDoc:
    doc_id: str
    filename: str
    path: Path
    media_type: str
    kind: str  # text | pdf | docx | image | binary
    text: str = ""
    error: str | None = None


@dataclass
class SessionDocs:
    session_id: str
    docs: list[StoredDoc] = field(default_factory=list)

    def dir(self) -> Path:
        d: Path = UPLOAD_DIR / self.session_id
        d.mkdir(parents=True, exist_ok=True)
        return d


_SESSIONS: dict[str, SessionDocs] = {}
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def get_session(session_id: str | None) -> SessionDocs:
    # Session ids become directory names: accept only safe ids, otherwise start a fresh session.
    sid: str = session_id if session_id and _SESSION_ID_RE.match(session_id) else str(uuid.uuid4())
    if sid not in _SESSIONS:
        _SESSIONS[sid] = SessionDocs(session_id=sid)
    return _SESSIONS[sid]


def _read_pdf(path: Path) -> str:
    reader: PdfReader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text).strip()


def _read_text(path: Path) -> str:
    raw: bytes = path.read_bytes()
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def save_upload(session: SessionDocs, filename: str, data: bytes) -> StoredDoc:
    safe: str = re.sub(r"[^\w.\-]+", "_", filename).strip("._") or "upload.bin"
    doc_id: str = uuid.uuid4().hex[:12]
    dest: Path = session.dir() / f"{doc_id}_{safe}"
    dest.write_bytes(data)

    suffix: str = dest.suffix.lower()
    media: str = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    kind: str = "binary"
    text: str = ""
    err: str | None = None

    try:
        if suffix in PDF_SUFFIXES:
            kind = "pdf"
            text = _read_pdf(dest)
        elif suffix in DOCX_SUFFIXES:
            kind = "docx"
            text = _read_docx(dest)
        elif suffix in TEXT_SUFFIXES:
            kind = "text"
            text = _read_text(dest)
        elif suffix in IMAGE_SUFFIXES:
            kind = "image"
            media = mimetypes.guess_type(safe)[0] or "image/png"
        else:
            kind = "binary"
            err = "Unsupported type; attached as opaque file name only."
    except Exception as exc:  # noqa: BLE001 — surface parse errors to UI
        err = f"Parse failed: {exc}"

    if text and len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n\n[truncated]"

    doc = StoredDoc(
        doc_id=doc_id,
        filename=safe,
        path=dest,
        media_type=media,
        kind=kind,
        text=text,
        error=err,
    )
    session.docs.append(doc)
    return doc


def delete_doc(session: SessionDocs, doc_id: str) -> bool:
    for i, d in enumerate(session.docs):
        if d.doc_id == doc_id:
            d.path.unlink(missing_ok=True)
            del session.docs[i]
            return True
    return False


def docs_context(session: SessionDocs) -> str:
    blocks: list[str] = []
    for d in session.docs:
        if d.kind == "image":
            blocks.append(f"### Image: {d.filename}\n(see attached image part)")
            continue
        body: str = d.text.strip() if d.text else f"(no extractable text{'; — ' + d.error if d.error else ''})"
        blocks.append(f"### File: {d.filename}\n{body}")
    if not blocks:
        return ""
    return (
        "The user uploaded the following documents. Use them as primary evidence "
        "when answering.\n\n" + "\n\n".join(blocks)
    )


def image_content_parts(session: SessionDocs) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for d in session.docs:
        if d.kind != "image":
            continue
        b64: str = base64.standard_b64encode(d.path.read_bytes()).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{d.media_type};base64,{b64}"},
            }
        )
    return parts
