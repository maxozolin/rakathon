from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).resolve().parent.parent.parent
CTIS_DB: Path = Path(os.environ.get("CTIS_DB", str(ROOT / "data" / "ctis" / "ctis.sqlite")))
CTGOV_DB: Path = Path(os.environ.get("CTGOV_DB", str(ROOT / "data" / "ctgov" / "ctgov.sqlite")))


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(f"Trial database not found: {path}")
    conn: sqlite3.Connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def catalog_stats() -> dict[str, Any]:
    out: dict[str, Any] = {"ctis_db": str(CTIS_DB), "ctgov_db": str(CTGOV_DB)}
    try:
        with _connect(CTIS_DB) as c:
            out["ctis_search"] = c.execute("SELECT COUNT(*) FROM trials_search").fetchone()[0]
            out["ctis_retrieve"] = c.execute("SELECT COUNT(*) FROM trials_retrieve").fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        out["ctis_error"] = str(exc)
    try:
        with _connect(CTGOV_DB) as c:
            out["ctgov_studies"] = c.execute("SELECT COUNT(*) FROM ctgov_studies").fetchone()[0]
            out["ctgov_motol"] = c.execute(
                "SELECT COUNT(*) FROM ctgov_studies WHERE motol_related=1"
            ).fetchone()[0]
            out["ctgov_recruiting"] = c.execute(
                "SELECT COUNT(*) FROM ctgov_studies WHERE overall_status='RECRUITING'"
            ).fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        out["ctgov_error"] = str(exc)
    return out


CZ_TERMS: tuple[tuple[str, str], ...] = (
    ("leukem", "leukemia"), ("leukém", "leukemia"), ("lymfom", "lymphoma"), ("myelom", "myeloma"),
    ("prs", "breast"), ("plic", "lung"), ("kolorekt", "colorectal"), ("tlust", "colorectal"),
    ("konečník", "rectal"), ("prostat", "prostat"), ("vaječník", "ovarian"), ("ovari", "ovarian"),
    ("děloh", "endometrial"), ("močov", "bladder"), ("ledvin", "renal"), ("žalud", "gastric"),
    ("slinivk", "pancrea"), ("pankrea", "pancrea"), ("jater", "hepat"), ("mozk", "brain"),
    ("melanom", "melanoma"), ("neuroblastom", "neuroblastoma"), ("sarkom", "sarcoma"),
    ("dětsk", "pediatric"), ("děti", "children"), ("dítě", "children"), ("rakovin", "cancer"),
    ("karcinom", "carcinoma"), ("nádor", "tumor"), ("srdc", "heart"), ("fibrilac", "fibrillation"),
)


def _tokens(query: str) -> list[str]:
    parts: list[str] = re.findall(r"[A-Za-zÀ-ž0-9\-]{3,}", query.lower())
    stop: set[str] = {
        "the", "and", "for", "with", "that", "this", "from", "have", "has", "are",
        "was", "were", "what", "which", "when", "where", "your", "you", "patient",
        "trial", "trials", "study", "studies", "clinical", "please", "find", "show",
        "about", "into", "can", "could", "would", "should", "open", "available",
        "recruiting", "right", "now", "currently", "any", "there", "some",
        # Czech filler words (otherwise OR-matching makes them hit almost every record)
        "jaké", "jaká", "jaký", "které", "která", "který", "studie", "studii", "studií", "klinické",
        "klinická", "klinických", "pro", "teď", "nyní", "právě", "aktuálně", "nabírají", "nabírá",
        "probíhají", "otevřené", "pacienty", "pacient", "mám", "mohu", "můžu", "prosím", "nějaké",
        "jsou", "být", "bych", "léčbu", "léčba",
    }
    out: list[str] = []
    for p in parts:
        if p in stop or p in out:
            continue
        # Registry text is English: map common Czech terms (any inflection) to their English stem.
        p = next((en for cz, en in CZ_TERMS if p.startswith(cz)), p)
        if p in out:
            continue
        out.append(p)
        if len(out) >= 8:
            break
    return out


def _score_sql(tokens: list[str], strong: list[str], weak: list[str]) -> tuple[str, list[Any]]:
    """Relevance = matched query terms, title/conditions counting double. Rank by it so that an
    OR-match on one generic word ("cancer") doesn't outrank a trial matching every term."""
    if not tokens:
        return "0", []
    parts: list[str] = []
    params: list[Any] = []
    for t in tokens:
        like = f"%{t}%"
        parts.append("(CASE WHEN " + " OR ".join(f"IFNULL({c},'') LIKE ?" for c in strong) + " THEN 2 "
                     "WHEN " + " OR ".join(f"IFNULL({c},'') LIKE ?" for c in weak) + " THEN 1 ELSE 0 END)")
        params.extend([like] * (len(strong) + len(weak)))
    return "(" + " + ".join(parts) + ")", params


def search_ctis(
    query: str,
    *,
    site_hint: str | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    tokens: list[str] = _tokens(query)
    if not tokens and not site_hint:
        return []
    clauses: list[str] = []
    params: list[Any] = []
    for t in tokens:
        like: str = f"%{t}%"
        clauses.append(
            "(s.title LIKE ? OR s.short_title LIKE ? OR IFNULL(s.medical_conditions,'') LIKE ? "
            "OR IFNULL(s.product,'') LIKE ? OR s.ct_number LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    # OR across tokens — AND is too strict for natural-language questions
    where: str = "(" + " OR ".join(clauses) + ")" if clauses else "1=1"
    site: str = (site_hint or "").strip().lower()
    score, score_params = _score_sql(
        tokens, ["s.title", "s.short_title", "s.medical_conditions"], ["s.product", "s.ct_number"])
    sql: str = f"""
        SELECT s.ct_number, s.short_title, s.title, s.ct_status, s.medical_conditions,
               s.trial_phase, s.gender, s.age_group, s.sponsor,
               r.inclusions_json, r.exclusions_json, r.sites_json, r.conditions_json
        FROM trials_search s
        LEFT JOIN trials_retrieve r ON r.ct_number = s.ct_number
        WHERE {where}
        ORDER BY {score} DESC, (r.ct_number IS NOT NULL) DESC, s.publish_date DESC
        LIMIT 40
    """
    params.extend(score_params)
    rows: list[dict[str, Any]] = []
    with _connect(CTIS_DB) as c:
        for row in c.execute(sql, params):
            sites_raw: str = row["sites_json"] or "[]"
            if site:
                if site not in sites_raw.lower() and site not in (row["title"] or "").lower():
                    # also check Motol/Prague aliases
                    aliases: dict[str, tuple[str, ...]] = {
                        "motol": ("motol",),
                        "homolka": ("homolka",),
                        "prague": ("prague", "praha"),
                        "praha": ("prague", "praha"),
                    }
                    keys: tuple[str, ...] = aliases.get(site, (site,))
                    if not any(a in sites_raw.lower() for a in keys):
                        continue
            inclusions: Any = []
            exclusions: Any = []
            try:
                inclusions = json.loads(row["inclusions_json"] or "[]")
            except json.JSONDecodeError:
                inclusions = []
            try:
                exclusions = json.loads(row["exclusions_json"] or "[]")
            except json.JSONDecodeError:
                exclusions = []
            sites: Any = []
            try:
                sites = json.loads(sites_raw)
            except json.JSONDecodeError:
                sites = []
            site_names: list[str] = []
            if isinstance(sites, list):
                for s in sites[:12]:
                    if isinstance(s, dict):
                        site_names.append(
                            f"{s.get('org') or s.get('name') or '?'} ({s.get('city') or '?'})"
                        )
            rows.append(
                {
                    "source": "ctis",
                    "id": row["ct_number"],
                    "title": row["short_title"] or row["title"],
                    "status": row["ct_status"],
                    "conditions": row["medical_conditions"] or row["conditions_json"],
                    "phase": row["trial_phase"],
                    "sex": row["gender"],
                    "age_group": row["age_group"],
                    "sponsor": row["sponsor"],
                    "sites_sample": site_names[:8],
                    "inclusion_preview": [
                        x if isinstance(x, str) else str(x) for x in (inclusions or [])[:4]
                    ],
                    "exclusion_preview": [
                        x if isinstance(x, str) else str(x) for x in (exclusions or [])[:3]
                    ],
                    "portal": f"https://euclinicaltrials.eu/ctis-public/view/{row['ct_number']}",
                }
            )
            if len(rows) >= limit:
                break
    return rows


def search_ctgov(
    query: str,
    *,
    motol_only: bool = False,
    homolka_only: bool = False,
    prague_only: bool = False,
    recruiting_only: bool = True,
    limit: int = 8,
) -> list[dict[str, Any]]:
    tokens: list[str] = _tokens(query)
    clauses: list[str] = []
    params: list[Any] = []
    if recruiting_only:
        clauses.append("overall_status = 'RECRUITING'")
    if motol_only:
        clauses.append("motol_related = 1")
    if homolka_only:
        clauses.append("homolka_related = 1")
    if prague_only:
        clauses.append("prague_related = 1")
    token_clauses: list[str] = []
    for t in tokens:
        like: str = f"%{t}%"
        token_clauses.append(
            "(brief_title LIKE ? OR official_title LIKE ? OR IFNULL(conditions_json,'') LIKE ? "
            "OR IFNULL(eligibility_text,'') LIKE ? OR nct_id LIKE ?)"
        )
        params.extend([like, like, like, like, like])
    if token_clauses:
        clauses.append("(" + " OR ".join(token_clauses) + ")")
    if not clauses:
        clauses.append("prague_related = 1")
    where: str = " AND ".join(clauses)
    score, score_params = _score_sql(
        tokens, ["brief_title", "official_title", "conditions_json"], ["eligibility_text", "nct_id"])
    sql: str = f"""
        SELECT nct_id, brief_title, overall_status, conditions_json, phase_json,
               sex, min_age, max_age, eligibility_text, motol_related, homolka_related,
               prague_related, eu_ct_ids_json, locations_json
        FROM ctgov_studies
        WHERE {where}
        ORDER BY {score} DESC, motol_related DESC, homolka_related DESC, nct_id
        LIMIT ?
    """
    params.extend(score_params)
    params.append(limit)
    rows: list[dict[str, Any]] = []
    with _connect(CTGOV_DB) as c:
        for row in c.execute(sql, params):
            elig: str = row["eligibility_text"] or ""
            rows.append(
                {
                    "source": "ctgov",
                    "id": row["nct_id"],
                    "title": row["brief_title"],
                    "status": row["overall_status"],
                    "conditions": row["conditions_json"],
                    "phase": row["phase_json"],
                    "sex": row["sex"],
                    "min_age": row["min_age"],
                    "max_age": row["max_age"],
                    "motol": bool(row["motol_related"]),
                    "homolka": bool(row["homolka_related"]),
                    "prague": bool(row["prague_related"]),
                    "eu_ct_ids": row["eu_ct_ids_json"],
                    "eligibility_preview": elig[:600],
                    "portal": f"https://clinicaltrials.gov/study/{row['nct_id']}",
                }
            )
    return rows


def get_trial(trial_id: str) -> dict[str, Any] | None:
    tid: str = trial_id.strip()
    if tid.upper().startswith("NCT"):
        hits: list[dict[str, Any]] = search_ctgov(tid, recruiting_only=False, limit=1)
        return hits[0] if hits else None
    hits_ctis: list[dict[str, Any]] = search_ctis(tid, limit=1)
    if hits_ctis and hits_ctis[0]["id"] == tid:
        # richer detail already
        return hits_ctis[0]
    # exact lookup
    with _connect(CTIS_DB) as c:
        row = c.execute(
            """
            SELECT s.ct_number, s.short_title, s.title, s.ct_status, s.medical_conditions,
                   s.trial_phase, r.inclusions_json, r.exclusions_json, r.sites_json
            FROM trials_search s
            LEFT JOIN trials_retrieve r ON r.ct_number = s.ct_number
            WHERE s.ct_number = ?
            """,
            (tid,),
        ).fetchone()
    if not row:
        return None
    return {
        "source": "ctis",
        "id": row["ct_number"],
        "title": row["short_title"] or row["title"],
        "status": row["ct_status"],
        "conditions": row["medical_conditions"],
        "phase": row["trial_phase"],
        "inclusions": json.loads(row["inclusions_json"] or "[]"),
        "exclusions": json.loads(row["exclusions_json"] or "[]"),
        "sites": json.loads(row["sites_json"] or "[]"),
        "portal": f"https://euclinicaltrials.eu/ctis-public/view/{row['ct_number']}",
    }


def auto_context_for_message(message: str, *, limit: int = 6) -> str:
    """Deterministic retrieval so the model cannot claim it has no catalog."""
    msg: str = message.lower()
    site_hint: str | None = None
    motol: bool = "motol" in msg
    homolka: bool = "homolka" in msg
    prague: bool = any(x in msg for x in ("prague", "praha", "praha"))
    if motol:
        site_hint = "motol"
    elif homolka:
        site_hint = "homolka"
    elif prague:
        site_hint = "prague"

    ctis_hits: list[dict[str, Any]] = search_ctis(message, site_hint=site_hint, limit=limit)
    ctgov_hits: list[dict[str, Any]] = search_ctgov(
        message,
        motol_only=motol,
        homolka_only=homolka and not motol,
        prague_only=prague and not motol and not homolka,
        recruiting_only=True,
        limit=limit,
    )
    stats: dict[str, Any] = catalog_stats()
    payload: dict[str, Any] = {
        "catalog_stats": stats,
        "ctis_hits": ctis_hits,
        "ctgov_hits": ctgov_hits,
    }
    if not ctis_hits and not ctgov_hits:
        # fallback: Motol recruiting slice so geography questions still get data
        payload["ctgov_hits"] = search_ctgov(
            "cancer oncology",
            motol_only=True,
            recruiting_only=True,
            limit=5,
        )
        payload["note"] = (
            "No strong keyword hits; included a Motol recruiting sample. "
            "Ask the user to narrow condition/site, or call get_trial with an ID."
        )
    raw: str = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(raw) <= 20000:
        return raw
    # Shrink previews rather than slicing mid-JSON
    for bucket in ("ctis_hits", "ctgov_hits"):
        for hit in payload.get(bucket, []):
            if isinstance(hit, dict):
                if "eligibility_preview" in hit:
                    hit["eligibility_preview"] = str(hit["eligibility_preview"])[:300]
                if "inclusion_preview" in hit and isinstance(hit["inclusion_preview"], list):
                    hit["inclusion_preview"] = hit["inclusion_preview"][:2]
                if "exclusion_preview" in hit and isinstance(hit["exclusion_preview"], list):
                    hit["exclusion_preview"] = hit["exclusion_preview"][:2]
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    # Still too long: drop whole hits (never cut the JSON mid-string).
    while len(raw) > 20000:
        buckets = [b for b in ("ctis_hits", "ctgov_hits") if payload.get(b)]
        if not buckets:
            break
        payload[max(buckets, key=lambda b: len(payload[b]))].pop()
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
    return raw
