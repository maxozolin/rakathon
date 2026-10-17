from __future__ import annotations

from typing import Any, AsyncIterator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import APIM_BASE_URL, api_key, chat_models
from .trials_db import auto_context_for_message


def model_meta(model_id: str) -> dict[str, Any]:
    for m in chat_models(multimodal_first=False):
        if m["id"] == model_id:
            return m
    raise KeyError(f"Unknown or non-chat model: {model_id}")


def make_llm(model_id: str) -> ChatOpenAI:
    _ = model_meta(model_id)
    key: str = api_key()
    # Many Rakathon deployments only accept the API default temperature.
    return ChatOpenAI(
        model=model_id,
        api_key=key,
        base_url=APIM_BASE_URL,
        max_completion_tokens=4096,
        default_headers={
            "api-key": key,
            "Ocp-Apim-Subscription-Key": key,
        },
    )


LANGUAGE_NAMES: dict[str, str] = {"cs": "Czech (čeština)", "en": "English"}


def system_prompt(doc_context: str, catalog_blob: str, language: str = "cs") -> str:
    base: str = (
        "You are Avicenna Chat for Rakathon — a clinical-trial assistant with "
        "**access to Avicenna's local trial databases** (SQLite mirrors of CTIS and "
        "ClinicalTrials.gov focused on Motol / Homolka / Prague / Czechia).\n\n"
        "CRITICAL:\n"
        "- Do **not** say you lack database access, cannot query ClinicalTrials.gov/CTIS, "
        "or that the user must search public portals for facts already present in "
        "LOCAL CATALOG RESULTS.\n"
        "- Answer from LOCAL CATALOG RESULTS. Cite trial IDs (NCT… / EU CT numbers) and "
        "portal links from those results.\n"
        "- If the catalog JSON has no relevant hits, say our **local ingest** had no match "
        "and ask the user to narrow condition/site — never claim the databases are unreachable.\n"
        "- Prefer Motol/Homolka/Prague when geography is unspecified for this demo.\n"
        "- Prefer evidence from uploaded patient documents when present.\n"
        "- Do not invent NCT/EU CT IDs, labs, or eligibility. This is decision-support, not enrollment.\n"
        "- Recruitment can change; treat status as from our ingest snapshot.\n"
        "\nAUDIENCE: the user is usually a patient or a family member, not a clinician.\n"
        f"- Reply in {LANGUAGE_NAMES.get(language, 'Czech (čeština)')} unless the user writes in another language.\n"
        "- Use plain words and short sentences; explain medical terms and abbreviations once.\n"
        "- Be warm and honest. Never promise eligibility, enrolment or benefit, and never state "
        "that a study drug works.\n"
        "- For each trial give: what it studies, the phase in plain words, why it may fit, what "
        "still needs checking, where it runs, and the ID with its link.\n"
        "- Never advise starting, stopping or changing treatment. Taking part is voluntary; the "
        "next step is always a conversation with the treating oncologist.\n"
    )
    if catalog_blob:
        base += "\n\n## LOCAL CATALOG RESULTS (from Avicenna SQLite)\n```json\n" + catalog_blob + "\n```\n"
    if doc_context:
        base += "\n\n" + doc_context
    return base


def build_messages(
    *,
    user_text: str,
    history: list[dict[str, str]],
    doc_context: str,
    image_parts: list[dict[str, Any]],
    multimodal: bool,
    catalog_blob: str,
    language: str = "cs",
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=system_prompt(doc_context, catalog_blob, language))]
    for turn in history[-20:]:
        role: str = turn.get("role", "")
        content: str = turn.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))

    if multimodal and image_parts:
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text or "(see attached images)"}]
        content.extend(image_parts)
        messages.append(HumanMessage(content=content))
    else:
        messages.append(HumanMessage(content=user_text))
    return messages


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                t: Any = part.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content or "")


async def stream_chat(
    model_id: str,
    messages: list[BaseMessage],
) -> AsyncIterator[str]:
    llm: ChatOpenAI = make_llm(model_id)
    async for chunk in llm.astream(messages):
        text: str = _message_text(chunk.content)
        if text:
            yield text


def retrieve_catalog(user_text: str) -> str:
    try:
        return auto_context_for_message(user_text)
    except Exception as exc:  # noqa: BLE001
        return (
            '{"error": "catalog retrieval failed: '
            + str(exc).replace('"', "'")
            + '"}'
        )
