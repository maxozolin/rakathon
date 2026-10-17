# Avicenna Chat — patient self-serve trial assistant

A small FastAPI + LangChain web app where patients and their families can ask, in Czech or English, about
clinical trials that are open in Czechia (Motol / Homolka / Prague first). They can also upload their
own medical report for context. Answers come from the Rakathon APIM OpenAI-compatible gateway (the same
gateway OpenCode uses). Each turn is grounded in a deterministic search of the local CT.gov and CTIS
SQLite mirrors.

## Features

- **Bilingual UI (CS / EN):** toggle in the header (default follows the browser, then Czech). The choice is sent
  with every message, and the model answers in that language.
- **Patient-oriented UX** in a calm "spa-town programme" look (mineral green colonnade header, answers on
  programme slips; see [`DESIGN.md`](DESIGN.md)):
  - a welcome screen with *Your programme* (three steps) and starter questions
  - each answer is a slip stamped *Avicenna · HH:MM*, with a copy button
  - drag-and-drop uploads, with document chips in the composer dock that you can remove
  - a "searching the registries" indicator and a stop button while an answer streams
  - Enter to send, Shift+Enter for a new line
  - responsive and keyboard/screen-reader friendly (`role="log"`, `aria-live`, labelled controls, reduced-motion support)
- **Markdown answers:** rendered with `marked` and sanitised with `DOMPurify`, both **vendored** in `static/vendor/`
  so the page makes no third-party requests. Links open in a new tab, wide tables scroll, and a reply wrapped in
  ```` ```markdown ```` is unwrapped. If the libraries fail to load, the answer is shown as plain text, never as raw HTML.
- **Documents:** PDF, DOCX, text/markdown/CSV/JSON/HTML and images (images need a multimodal model, noted “reads images” in Settings).
- **Grounding:** each turn runs a keyword search over CTIS and CT.gov (`server/trials_db.py`). Filler words in
  Czech and English are dropped, and common Czech medical terms are mapped to their English stems
  (`CZ_TERMS`; e.g. "leukemií" → leukemia, "prsu" → breast). Hits are ranked by how many terms match, with
  title/conditions counting double. The results go into the system prompt as `LOCAL CATALOG RESULTS` (≤20 kB,
  trimmed hit by hit; the GPT-6 APIM deployments don't support function tools).
- **Model choice:** tucked away under *Settings*, from `models.json`. EU-zone multimodal models are listed first;
  image-generation models are excluded.

## Run

### Docker (what runs on :8080)

Needs `../.env` with `AZURE_LLM_API_KEY`.

```bash
cd chat-app
docker compose up --build -d      # rebuild after any change: server/ and static/ are baked into the image
```

Open http://localhost:8080. Compose mounts `../data/ctis` and `../data/ctgov` read-only and persists uploads in
`./data/uploads`.

### Locally (uv)

```bash
cd chat-app
uv venv && uv pip install -r requirements.txt
set -a && source ../.env && set +a          # or rely on ../.opencode-secrets/apim-api-key
.venv/bin/uvicorn server.main:app --reload --port 8080
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `AZURE_LLM_API_KEY` | — (fallback: `../.opencode-secrets/apim-api-key`) | APIM key, sent as `api-key` and `Ocp-Apim-Subscription-Key` |
| `AZURE_LLM_API_ENDPOINT` | `https://apim-rakathon-q7146n.azure-api.net/openai/v1` | OpenAI-compatible base URL |
| `DEFAULT_MODEL` | `gpt-6-1-sol-dz-eu` | preselected model |
| `CTIS_DB` / `CTGOV_DB` | `../data/ctis/ctis.sqlite`, `../data/ctgov/ctgov.sqlite` | trial mirrors (opened read-only) |
| `UPLOAD_DIR` | `./data/uploads` | where uploaded files are written |
| `SSL_CERT_FILE` | — | set to the system CA bundle (e.g. `/etc/ssl/certs/ca-certificates.crt`) if APIM calls fail with `Connection error` on hosts whose CA isn't in `certifi` |

## API

| Endpoint | Purpose |
|---|---|
| `GET /` | the UI (`static/index.html`) |
| `GET /api/health` | status + catalog row counts |
| `GET /api/models` | `{default, chat: [...], all: [...]}` |
| `POST /api/upload` | multipart `file` (+ optional `session_id`); max 25 MB → `{session_id, doc, docs}` |
| `GET /api/session/{session_id}/docs` | documents of a session (an unknown id returns a *new* empty session) |
| `DELETE /api/session/{session_id}/docs/{doc_id}` | remove a document (file deleted from disk) → `{session_id, docs}` |
| `POST /api/chat` | JSON `{message, model, session_id, history, language: "cs"\|"en"}` → Server-Sent Events |

SSE events, one JSON object per `data:` line:
- `{"type":"meta","session_id","model"}`
- `{"type":"token","text"}` (repeated)
- then `{"type":"done"}` or `{"type":"error","message"}`

`history` is a list of `{role: "user"|"assistant", content}`; the server keeps the last 20 turns.

## How it works

```
browser (static/index.html)
  │  POST /api/chat {message, history, language, session_id}
  ▼
server/main.py ── trials_db.auto_context_for_message(message)   keyword search, CTIS + CT.gov, ≤20 kB JSON
            ├── documents.docs_context(session)                 extracted text of uploads (≤120k chars each)
            ├── documents.image_content_parts(session)          base64 images (multimodal models only)
            └── llm.build_messages → llm.stream_chat            LangChain ChatOpenAI → APIM, streamed back as SSE
```

| File | Role |
|---|---|
| `server/main.py` | FastAPI routes, SSE streaming |
| `server/llm.py` | system prompt (grounding rules + patient-communication rules + reply language), LangChain client |
| `server/trials_db.py` | read-only SQLite search; Motol/Homolka/Prague hints taken from the message |
| `server/documents.py` | upload storage and text extraction (pypdf, python-docx); in-memory session registry |
| `server/config.py` | env/config, `models.json` loading and ordering |
| `static/index.html` | the whole UI (vanilla JS, no build step); strings in the `I18N` object |
| `static/fonts/` | self-hosted Alegreya Sans 700/800 (latin + latin-ext, OFL) for headings |
| `static/logo-mark.png` | logo as an alpha mask (coloured with CSS) for the header and answer slips |
| `DESIGN.md` | the chat UI's visual system (palette, type, components, motion) |

### Privacy and data handling

- **Sessions:** the session id and chat history live in the browser's `sessionStorage`, so closing the tab
  forgets them. Language and model choice are in `localStorage`.
- **Server state:** the server keeps sessions in memory, so a restart forgets them and the UI starts a fresh session.
- **Uploaded files stay on disk.** They remain under `UPLOAD_DIR/<session_id>/` until removed in the UI or cleaned
  up by an operator. Session ids are validated (`[A-Za-z0-9-]{8,64}`) before they are used as directory names.
- **What reaches the model:** document text and images are sent to the selected model through APIM, so prefer the
  EU Data Zone models. The UI asks patients not to upload national identifiers.
- **No authentication.** Run it only on a trusted network or behind a proxy that adds auth.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Answers show raw `**markdown**` | Old image or cached page from before the libraries were vendored: `docker compose up --build -d`, then hard-reload |
| "Sorry, we couldn't get an answer" | Look in the browser console / server log. Common causes: APIM quota exceeded (403), a missing key, or TLS (see `SSL_CERT_FILE`) |
| An uploaded image is ignored | The selected model is not multimodal; pick one marked ◎ in *Settings* |
| Catalog counts missing in `/api/health` | `CTIS_DB` / `CTGOV_DB` paths are wrong or the volumes aren't mounted |

## Customising

- **Texts and translations:** edit the `I18N.cs` / `I18N.en` objects in `static/index.html`. Both languages must
  define the same keys.
- **Assistant behaviour:** edit `system_prompt()` in `server/llm.py`.
- **Models:** edit `models.json` (`kind: "chat"` to show a model, `preferred` / `zone` / `multimodal` for ordering
  and the ◎ marker).
- **Vendored libraries:** `marked` 15.0.12 and `DOMPurify` 3.2.6 (licenses next to them). To upgrade, replace the
  files and update the two `<script>` tags.
