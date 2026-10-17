#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Ingest CTIS public search overviews into SQLite; optional full retrieve.

There is no CIRCABC / bulk dump for the CTIS public catalog. Search and UI
exports are capped (~10k per query). Shard by status code to cover the full
registry (~12k+ trials), store overviews first, then retrieve on demand.

API:
  POST https://euclinicaltrials.eu/ctis-public-api/search
  GET  https://euclinicaltrials.eu/ctis-public-api/retrieve/{ctNumber}
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Final

CTIS_SEARCH: Final[str] = "https://euclinicaltrials.eu/ctis-public-api/search"
CTIS_RETRIEVE: Final[str] = "https://euclinicaltrials.eu/ctis-public-api/retrieve/{ct}"
PAGE_SIZE: Final[int] = 100
# Soft rate limit; public API has tolerated ~0.3–0.5s in community reports.
SLEEP_S: Final[float] = 0.35
USER_AGENT: Final[str] = "Mozilla/5.0 (compatible; rakathon-avicenna/1.0)"

# Empty criteria template (nulls omitted by CTIS when absent; we send known keys).
STATUS_CODES: Final[list[int]] = list(range(1, 12))


def http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    retries: int = 4,
) -> dict[str, Any]:
    data: bytes | None = None
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last_err: Exception | None = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw: bytes = resp.read()
            parsed: object = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError(f"expected JSON object from {url}")
            return parsed
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(SLEEP_S * (attempt + 1) * 2)
    assert last_err is not None
    raise last_err


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS meta (
          key   TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS trials_search (
          ct_number        TEXT PRIMARY KEY,
          short_title      TEXT,
          title            TEXT,
          ct_status        TEXT,
          ct_status_code   INTEGER,
          medical_conditions TEXT,
          therapeutic_areas  TEXT,
          trial_phase      TEXT,
          sponsor          TEXT,
          sponsor_type     TEXT,
          countries_json   TEXT,
          age_group        TEXT,
          gender           TEXT,
          trial_region     TEXT,
          decision_date    TEXT,
          publish_date     TEXT,
          product          TEXT,
          primary_endpoint TEXT,
          overview_json    TEXT NOT NULL,
          search_shard     TEXT,
          ingested_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trials_retrieve (
          ct_number     TEXT PRIMARY KEY,
          status        TEXT,
          public_title  TEXT,
          short_title   TEXT,
          conditions_json TEXT,
          inclusions_json TEXT,
          exclusions_json TEXT,
          sites_json      TEXT,
          retrieve_json   TEXT NOT NULL,
          retrieved_at    TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY (ct_number) REFERENCES trials_search(ct_number)
        );

        CREATE INDEX IF NOT EXISTS idx_trials_search_status
          ON trials_search(ct_status_code);
        CREATE INDEX IF NOT EXISTS idx_trials_search_sponsor
          ON trials_search(sponsor);
        """
    )
    conn.commit()


def upsert_overview(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    shard: str,
) -> None:
    ct: str | None = row.get("ctNumber")
    if not ct:
        return
    countries = row.get("trialCountries")
    conn.execute(
        """
        INSERT INTO trials_search (
          ct_number, short_title, title, ct_status, ct_status_code,
          medical_conditions, therapeutic_areas, trial_phase, sponsor, sponsor_type,
          countries_json, age_group, gender, trial_region, decision_date, publish_date,
          product, primary_endpoint, overview_json, search_shard, ingested_at
        ) VALUES (
          ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now')
        )
        ON CONFLICT(ct_number) DO UPDATE SET
          short_title=excluded.short_title,
          title=excluded.title,
          ct_status=excluded.ct_status,
          ct_status_code=excluded.ct_status_code,
          medical_conditions=excluded.medical_conditions,
          therapeutic_areas=excluded.therapeutic_areas,
          trial_phase=excluded.trial_phase,
          sponsor=excluded.sponsor,
          sponsor_type=excluded.sponsor_type,
          countries_json=excluded.countries_json,
          age_group=excluded.age_group,
          gender=excluded.gender,
          trial_region=excluded.trial_region,
          decision_date=excluded.decision_date,
          publish_date=excluded.publish_date,
          product=excluded.product,
          primary_endpoint=excluded.primary_endpoint,
          overview_json=excluded.overview_json,
          search_shard=excluded.search_shard,
          ingested_at=datetime('now')
        """,
        (
            ct,
            row.get("shortTitle"),
            row.get("ctTitle") or row.get("title"),
            str(row.get("ctStatus")) if row.get("ctStatus") is not None else None,
            int(row["ctStatus"]) if isinstance(row.get("ctStatus"), int) else None,
            _as_text(row.get("conditions") or row.get("medicalConditions")),
            _as_text(row.get("therapeuticAreas")),
            row.get("trialPhase"),
            row.get("sponsor"),
            row.get("sponsorType"),
            json.dumps(countries, ensure_ascii=False) if countries is not None else None,
            row.get("ageGroup"),
            row.get("gender"),
            str(row.get("trialRegion")) if row.get("trialRegion") is not None else None,
            row.get("decisionDateOverall") or row.get("decisionDate"),
            row.get("lastPublicationUpdate") or row.get("publishDate"),
            row.get("product"),
            row.get("primaryEndPoint") or row.get("endPoint"),
            json.dumps(row, ensure_ascii=False),
            shard,
        ),
    )


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(
                    str(
                        item.get("medicalCondition")
                        or item.get("name")
                        or item.get("termName")
                        or item
                    )
                )
            else:
                parts.append(str(item))
        return "; ".join(parts)
    return str(value)


def search_page(
    criteria: dict[str, Any],
    page: int,
    size: int = PAGE_SIZE,
) -> dict[str, Any]:
    return http_json(
        "POST",
        CTIS_SEARCH,
        {
            "pagination": {"page": page, "size": size},
            "sort": {"property": "decisionDate", "direction": "DESC"},
            "searchCriteria": criteria,
        },
    )


def ingest_search_shard(
    conn: sqlite3.Connection,
    criteria: dict[str, Any],
    shard: str,
    *,
    max_pages: int | None = None,
) -> int:
    page: int = 1
    total_saved: int = 0
    while True:
        payload = search_page(criteria, page)
        pagination = payload.get("pagination") or {}
        rows = payload.get("data") or []
        total_records = int(pagination.get("totalRecords") or 0)
        total_pages = int(pagination.get("totalPages") or 0)
        if page == 1:
            print(
                f"[{shard}] totalRecords={total_records} totalPages={total_pages}",
                flush=True,
            )
            if total_records > 10_000:
                print(
                    f"[{shard}] WARNING: >10k results; API may truncate — refine shard",
                    flush=True,
                )
        if not rows:
            break
        for row in rows:
            if isinstance(row, dict):
                upsert_overview(conn, row, shard)
                total_saved += 1
        conn.commit()
        print(f"[{shard}] page {page}/{total_pages or '?'} (+{len(rows)})", flush=True)
        next_page = bool(pagination.get("nextPage"))
        page += 1
        if not next_page:
            break
        if max_pages is not None and page > max_pages:
            break
        time.sleep(SLEEP_S)
    return total_saved


def cmd_search_all(conn: sqlite3.Connection) -> None:
    """Shard by public status code so each query stays under the ~10k cap."""
    saved: int = 0
    for code in STATUS_CODES:
        criteria: dict[str, Any] = {"status": [code]}
        saved += ingest_search_shard(conn, criteria, shard=f"status:{code}")
        time.sleep(SLEEP_S)
    # Catch anything with null/odd status via broad containAny unlikely miss —
    # also store a Czechia-focused shard for Avicenna priority.
    saved += ingest_search_shard(
        conn, {"containAll": "Czechia"}, shard="containAll:Czechia"
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES('last_search_all', datetime('now'))"
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM trials_search").fetchone()[0]
    print(f"Done search ingest. upserts≈{saved} distinct_rows={n}", flush=True)


def cmd_search_query(conn: sqlite3.Connection, contain_all: str | None, condition: str | None) -> None:
    criteria: dict[str, Any] = {}
    if contain_all:
        criteria["containAll"] = contain_all
    if condition:
        criteria["medicalCondition"] = condition
    if not criteria:
        raise SystemExit("need --contain-all and/or --condition")
    shard = "query:" + "&".join(f"{k}={v}" for k, v in criteria.items())
    n = ingest_search_shard(conn, criteria, shard=shard)
    print(f"Saved≈{n} for {shard}", flush=True)


def _extract_retrieve_fields(doc: dict[str, Any]) -> dict[str, Any]:
    ct = str(doc.get("ctNumber") or "")
    status = doc.get("ctStatus")
    public_title = None
    short_title = None
    conditions: list[str] = []
    inclusions: list[str] = []
    exclusions: list[str] = []
    sites: list[dict[str, Any]] = []
    try:
        app = doc["authorizedApplication"]["authorizedPartI"]
        ids = app["trialDetails"]["clinicalTrialIdentifiers"]
        public_title = ids.get("publicTitle")
        short_title = ids.get("shortTitle")
        info = app["trialDetails"]["trialInformation"]
        for c in (info.get("medicalCondition") or {}).get("partIMedicalConditions") or []:
            if isinstance(c, dict) and c.get("medicalCondition"):
                conditions.append(str(c["medicalCondition"]))
        elig = info.get("eligibilityCriteria") or {}
        for item in elig.get("principalInclusionCriteria") or []:
            if isinstance(item, dict) and item.get("principalInclusionCriteria"):
                inclusions.append(str(item["principalInclusionCriteria"]))
        for item in elig.get("principalExclusionCriteria") or []:
            if isinstance(item, dict) and item.get("principalExclusionCriteria"):
                exclusions.append(str(item["principalExclusionCriteria"]))
        for part_ii in doc["authorizedApplication"].get("authorizedPartsII") or []:
            msc = part_ii.get("mscInfo") or {}
            country = msc.get("countryName") or msc.get("mscName")
            for site in part_ii.get("trialSites") or []:
                org_info = (site.get("organisationAddressInfo") or {})
                org = org_info.get("organisation") or {}
                addr = org_info.get("address") or {}
                sites.append(
                    {
                        "country": country,
                        "org": org.get("name") or org.get("organisationName"),
                        "city": addr.get("city") or addr.get("town"),
                        "department": site.get("departmentName"),
                    }
                )
    except (KeyError, TypeError):
        pass
    return {
        "ct_number": ct,
        "status": status,
        "public_title": public_title,
        "short_title": short_title,
        "conditions_json": json.dumps(conditions, ensure_ascii=False),
        "inclusions_json": json.dumps(inclusions, ensure_ascii=False),
        "exclusions_json": json.dumps(exclusions, ensure_ascii=False),
        "sites_json": json.dumps(sites, ensure_ascii=False),
        "retrieve_json": json.dumps(doc, ensure_ascii=False),
    }


def cmd_retrieve(
    conn: sqlite3.Connection,
    *,
    only_czechia: bool,
    limit: int | None,
    missing_only: bool,
) -> None:
    sql = "SELECT ct_number, countries_json FROM trials_search"
    clauses: list[str] = []
    if missing_only:
        clauses.append(
            "ct_number NOT IN (SELECT ct_number FROM trials_retrieve)"
        )
    if only_czechia:
        clauses.append("countries_json LIKE '%Czechia%'")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY ct_number"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    print(f"Retrieving {len(rows)} trials…", flush=True)
    for i, (ct_number, _countries) in enumerate(rows, start=1):
        url = CTIS_RETRIEVE.format(ct=ct_number)
        try:
            doc = http_json("GET", url)
        except Exception as exc:
            print(f"FAIL {ct_number}: {exc}", flush=True)
            time.sleep(SLEEP_S)
            continue
        fields = _extract_retrieve_fields(doc)
        conn.execute(
            """
            INSERT INTO trials_retrieve (
              ct_number, status, public_title, short_title,
              conditions_json, inclusions_json, exclusions_json, sites_json,
              retrieve_json, retrieved_at
            ) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(ct_number) DO UPDATE SET
              status=excluded.status,
              public_title=excluded.public_title,
              short_title=excluded.short_title,
              conditions_json=excluded.conditions_json,
              inclusions_json=excluded.inclusions_json,
              exclusions_json=excluded.exclusions_json,
              sites_json=excluded.sites_json,
              retrieve_json=excluded.retrieve_json,
              retrieved_at=datetime('now')
            """,
            (
                fields["ct_number"],
                fields["status"],
                fields["public_title"],
                fields["short_title"],
                fields["conditions_json"],
                fields["inclusions_json"],
                fields["exclusions_json"],
                fields["sites_json"],
                fields["retrieve_json"],
            ),
        )
        if i % 10 == 0:
            conn.commit()
            print(f"… {i}/{len(rows)}", flush=True)
        time.sleep(SLEEP_S)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM trials_retrieve").fetchone()[0]
    print(f"Done. trials_retrieve={n}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "ctis" / "ctis.sqlite",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create SQLite schema")
    sub.add_parser("search-all", help="Ingest all overviews (shard by status)")
    q = sub.add_parser("search", help="Ingest one search query")
    q.add_argument("--contain-all", default=None)
    q.add_argument("--condition", default=None)

    r = sub.add_parser("retrieve", help="Full retrieve for rows already in search table")
    r.add_argument("--czechia", action="store_true", help="Only trials listing Czechia")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument(
        "--missing-only",
        action="store_true",
        default=True,
        help="Skip ct_numbers already in trials_retrieve (default)",
    )
    r.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch even if already retrieved",
    )

    s = sub.add_parser("stats", help="Row counts")
    _ = s

    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        if args.cmd == "init":
            print(f"Initialized {args.db}")
        elif args.cmd == "search-all":
            cmd_search_all(conn)
        elif args.cmd == "search":
            cmd_search_query(conn, args.contain_all, args.condition)
        elif args.cmd == "retrieve":
            cmd_retrieve(
                conn,
                only_czechia=bool(args.czechia),
                limit=args.limit,
                missing_only=not bool(args.refresh),
            )
        elif args.cmd == "stats":
            for table in ("trials_search", "trials_retrieve"):
                n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"{table}: {n}")
            cz = conn.execute(
                "SELECT COUNT(*) FROM trials_search WHERE countries_json LIKE '%Czechia%'"
            ).fetchone()[0]
            print(f"trials_search with Czechia in countries: {cz}")
        else:
            raise SystemExit(f"unknown cmd {args.cmd}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
