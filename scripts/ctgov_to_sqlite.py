#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Ingest ClinicalTrials.gov (API v2) into SQLite for Avicenna geo seeds.

Default scope: Motol / Homolka / Prague recruiting+active studies.
Stores list hits + full study JSON; extracts EU CT / EudraCT secondary IDs
for crosswalk to CTIS (`data/ctis/ctis.sqlite`).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Final, Iterator

API: Final[str] = "https://clinicaltrials.gov/api/v2/studies"
SLEEP_S: Final[float] = 0.25
USER_AGENT: Final[str] = "Mozilla/5.0 (compatible; rakathon-avicenna/1.0)"
CTIS_EUCT: Final[re.Pattern[str]] = re.compile(r"20\d{2}-\d{6}-\d{2}-\d{2}")
EUDRACT: Final[re.Pattern[str]] = re.compile(r"20\d{2}-\d{6}-\d{2}(?!-\d)")

# Seed queries for Prague / Motol / Homolka (Avicenna ladder).
DEFAULT_QUERIES: Final[list[tuple[str, str]]] = [
    ("motol_prague", "AREA[LocationFacility]Motol AND AREA[LocationCity]Prague"),
    ("homolka_prague", "AREA[LocationFacility]Homolka AND AREA[LocationCity]Prague"),
    ("motol_any", "AREA[LocationFacility]Motol"),
    ("prague_oncology", "AREA[LocationCity]Prague AND (cancer OR oncology OR carcinoma OR lymphoma OR leukemia OR sarcoma OR melanoma OR tumour OR tumor)"),
]


def http_json(url: str, *, retries: int = 4) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                parsed: object = json.loads(resp.read().decode("utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError("expected JSON object")
            return parsed
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(SLEEP_S * (attempt + 1) * 2)
    assert last is not None
    raise last


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ctgov_studies (
          nct_id            TEXT PRIMARY KEY,
          brief_title       TEXT,
          official_title    TEXT,
          overall_status    TEXT,
          conditions_json   TEXT,
          phase_json        TEXT,
          eligibility_text  TEXT,
          sex               TEXT,
          min_age           TEXT,
          max_age           TEXT,
          std_ages_json     TEXT,
          locations_json    TEXT,
          prague_related    INTEGER NOT NULL DEFAULT 0,
          motol_related     INTEGER NOT NULL DEFAULT 0,
          homolka_related   INTEGER NOT NULL DEFAULT 0,
          eu_ct_ids_json    TEXT,
          eudract_ids_json  TEXT,
          query_shards      TEXT,
          study_json        TEXT NOT NULL,
          ingested_at       TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_ctgov_status ON ctgov_studies(overall_status);
        CREATE INDEX IF NOT EXISTS idx_ctgov_prague ON ctgov_studies(prague_related);
        CREATE INDEX IF NOT EXISTS idx_ctgov_motol ON ctgov_studies(motol_related);
        """
    )
    conn.commit()


def iter_studies(query: str, statuses: list[str] | None = None) -> Iterator[dict[str, Any]]:
    page_token: str | None = None
    while True:
        params: dict[str, str] = {
            "query.term": query,
            "pageSize": "100",
            "countTotal": "true",
            "format": "json",
        }
        if statuses:
            # API accepts repeated filter — use comma for overallStatus in v2
            params["filter.overallStatus"] = "|".join(statuses)
        if page_token:
            params["pageToken"] = page_token
        url = API + "?" + urllib.parse.urlencode(params)
        payload = http_json(url)
        for study in payload.get("studies") or []:
            if isinstance(study, dict):
                yield study
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        time.sleep(SLEEP_S)


def _locations(study: dict[str, Any]) -> list[dict[str, Any]]:
    locs = (
        study.get("protocolSection", {})
        .get("contactsLocationsModule", {})
        .get("locations")
        or []
    )
    out: list[dict[str, Any]] = []
    for loc in locs:
        if not isinstance(loc, dict):
            continue
        out.append(
            {
                "facility": loc.get("facility"),
                "city": loc.get("city"),
                "state": loc.get("state"),
                "country": loc.get("country"),
                "status": loc.get("status"),
                "zip": loc.get("zip"),
            }
        )
    return out


def _flags(locations: list[dict[str, Any]]) -> tuple[int, int, int]:
    prague = motol = homolka = 0
    for loc in locations:
        city = (loc.get("city") or "").lower()
        fac = (loc.get("facility") or "").lower()
        country = (loc.get("country") or "").lower()
        if "prague" in city or "praha" in city:
            prague = 1
        if "motol" in fac:
            motol = 1
            if country.startswith("czech"):
                prague = 1
        if "homolka" in fac:
            homolka = 1
            if country.startswith("czech"):
                prague = 1
    return prague, motol, homolka


def _secondary_ids(study: dict[str, Any]) -> tuple[list[str], list[str]]:
    ident = study.get("protocolSection", {}).get("identificationModule", {})
    blob = json.dumps(ident, ensure_ascii=False)
    eu_ct = list(dict.fromkeys(CTIS_EUCT.findall(blob)))
    eudra = [
        x
        for x in dict.fromkeys(EUDRACT.findall(blob))
        if x not in {e.rsplit("-", 1)[0] for e in eu_ct} and not any(x == e[:14] for e in eu_ct)
    ]
    # Prefer typed secondaryIdInfos
    for sec in ident.get("secondaryIdInfos") or []:
        if not isinstance(sec, dict):
            continue
        sid = str(sec.get("id") or "").strip()
        stype = str(sec.get("type") or "").upper()
        if CTIS_EUCT.fullmatch(sid) or stype == "CTIS":
            if sid and sid not in eu_ct:
                eu_ct.append(sid)
        if stype in {"EUDRACT_NUMBER", "EUDRACT"} or (
            EUDRACT.fullmatch(sid) and sid.count("-") == 2
        ):
            if sid and sid not in eudra and sid not in eu_ct:
                eudra.append(sid)
    return eu_ct, eudra


def upsert_study(conn: sqlite3.Connection, study: dict[str, Any], shard: str) -> str | None:
    proto = study.get("protocolSection") or {}
    ident = proto.get("identificationModule") or {}
    nct = ident.get("nctId")
    if not nct:
        return None
    status_mod = proto.get("statusModule") or {}
    cond_mod = proto.get("conditionsModule") or {}
    elig = proto.get("eligibilityModule") or {}
    design = proto.get("designModule") or {}
    locations = _locations(study)
    prague, motol, homolka = _flags(locations)
    eu_ct, eudra = _secondary_ids(study)

    existing = conn.execute(
        "SELECT query_shards FROM ctgov_studies WHERE nct_id=?", (nct,)
    ).fetchone()
    shards: list[str] = []
    if existing and existing[0]:
        try:
            shards = json.loads(existing[0])
        except json.JSONDecodeError:
            shards = [existing[0]]
    if shard not in shards:
        shards.append(shard)

    conn.execute(
        """
        INSERT INTO ctgov_studies (
          nct_id, brief_title, official_title, overall_status,
          conditions_json, phase_json, eligibility_text, sex, min_age, max_age,
          std_ages_json, locations_json, prague_related, motol_related, homolka_related,
          eu_ct_ids_json, eudract_ids_json, query_shards, study_json, ingested_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(nct_id) DO UPDATE SET
          brief_title=excluded.brief_title,
          official_title=excluded.official_title,
          overall_status=excluded.overall_status,
          conditions_json=excluded.conditions_json,
          phase_json=excluded.phase_json,
          eligibility_text=excluded.eligibility_text,
          sex=excluded.sex,
          min_age=excluded.min_age,
          max_age=excluded.max_age,
          std_ages_json=excluded.std_ages_json,
          locations_json=excluded.locations_json,
          prague_related=MAX(prague_related, excluded.prague_related),
          motol_related=MAX(motol_related, excluded.motol_related),
          homolka_related=MAX(homolka_related, excluded.homolka_related),
          eu_ct_ids_json=excluded.eu_ct_ids_json,
          eudract_ids_json=excluded.eudract_ids_json,
          query_shards=excluded.query_shards,
          study_json=excluded.study_json,
          ingested_at=datetime('now')
        """,
        (
            nct,
            ident.get("briefTitle"),
            ident.get("officialTitle"),
            status_mod.get("overallStatus"),
            json.dumps(cond_mod.get("conditions") or [], ensure_ascii=False),
            json.dumps(design.get("phases") or [], ensure_ascii=False),
            elig.get("eligibilityCriteria"),
            elig.get("sex"),
            elig.get("minimumAge"),
            elig.get("maximumAge"),
            json.dumps(elig.get("stdAges") or [], ensure_ascii=False),
            json.dumps(locations, ensure_ascii=False),
            prague,
            motol,
            homolka,
            json.dumps(eu_ct, ensure_ascii=False),
            json.dumps(eudra, ensure_ascii=False),
            json.dumps(shards, ensure_ascii=False),
            json.dumps(study, ensure_ascii=False),
        ),
    )
    return nct


def cmd_ingest(
    conn: sqlite3.Connection,
    *,
    queries: list[tuple[str, str]],
    statuses: list[str],
) -> None:
    total = 0
    for shard, query in queries:
        print(f"[{shard}] query={query!r} statuses={statuses}", flush=True)
        n = 0
        for study in iter_studies(query, statuses=statuses):
            nct = upsert_study(conn, study, shard)
            if nct:
                n += 1
                total += 1
            if n % 25 == 0:
                conn.commit()
                print(f"[{shard}] … {n}", flush=True)
        conn.commit()
        print(f"[{shard}] upserts={n}", flush=True)
        time.sleep(SLEEP_S)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES('last_ingest', datetime('now'))"
    )
    conn.commit()
    distinct = conn.execute("SELECT COUNT(*) FROM ctgov_studies").fetchone()[0]
    print(f"Done. upsert_events≈{total} distinct={distinct}", flush=True)


def cmd_stats(conn: sqlite3.Connection, ctis_db: Path | None) -> None:
    n = conn.execute("SELECT COUNT(*) FROM ctgov_studies").fetchone()[0]
    prague = conn.execute(
        "SELECT COUNT(*) FROM ctgov_studies WHERE prague_related=1"
    ).fetchone()[0]
    motol = conn.execute(
        "SELECT COUNT(*) FROM ctgov_studies WHERE motol_related=1"
    ).fetchone()[0]
    homolka = conn.execute(
        "SELECT COUNT(*) FROM ctgov_studies WHERE homolka_related=1"
    ).fetchone()[0]
    with_eu = conn.execute(
        "SELECT COUNT(*) FROM ctgov_studies WHERE eu_ct_ids_json NOT IN ('[]', '')"
    ).fetchone()[0]
    print(f"ctgov_studies: {n}")
    print(f"  prague_related: {prague}")
    print(f"  motol_related: {motol}")
    print(f"  homolka_related: {homolka}")
    print(f"  with CTIS EUCT secondary id: {with_eu}")
    if ctis_db and ctis_db.is_file():
        ctis = sqlite3.connect(ctis_db)
        rows = conn.execute(
            "SELECT nct_id, eu_ct_ids_json FROM ctgov_studies WHERE eu_ct_ids_json NOT IN ('[]','')"
        ).fetchall()
        linked = 0
        missing = 0
        for nct, eu_json in rows:
            ids = json.loads(eu_json)
            hit = False
            for eu in ids:
                if ctis.execute(
                    "SELECT 1 FROM trials_search WHERE ct_number=?", (eu,)
                ).fetchone():
                    hit = True
                    break
            if hit:
                linked += 1
            else:
                missing += 1
        print(f"  crosswalk to CTIS search: linked={linked} eu_id_not_in_ctis={missing}")
        ctis.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "ctgov" / "ctgov.sqlite",
    )
    parser.add_argument(
        "--ctis-db",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "ctis" / "ctis.sqlite",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    ing = sub.add_parser("ingest", help="Pull CT.gov studies for default Prague/Motol seeds")
    ing.add_argument(
        "--status",
        action="append",
        dest="statuses",
        default=None,
        help="Overall status filter (repeatable). Default: RECRUITING and ACTIVE_NOT_RECRUITING",
    )
    sub.add_parser("stats")
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        if args.cmd == "init":
            print(f"Initialized {args.db}")
        elif args.cmd == "ingest":
            statuses = args.statuses or ["RECRUITING", "ACTIVE_NOT_RECRUITING"]
            cmd_ingest(conn, queries=DEFAULT_QUERIES, statuses=statuses)
        elif args.cmd == "stats":
            cmd_stats(conn, args.ctis_db)
        else:
            raise SystemExit(args.cmd)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
