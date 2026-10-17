"""Local trial catalog: one searchable index over the CT.gov and CTIS registry snapshots.

The source databases are produced by `scripts/ctgov_to_sqlite.py` and `scripts/ctis_to_sqlite.py`.
They are large (CTIS carries full dossiers), so this module distils them once into a small
SQLite file with an FTS5 index and the fields the matcher needs:

- header: title, phase, conditions, sponsor, products, registry status;
- availability: `available` (open now or authorised and about to open) and `recruiting`;
- geography: sites, and `geo_rank` per MISSION.md
  (1 Motol/Homolka, 2 other Prague, 3 Brno/Ostrava, 4 rest of Czechia, 5 elsewhere/unknown);
- eligibility: structured age/sex plus the verbatim inclusion/exclusion bullets.

Only public registry data is stored here. No patient data ever enters the catalog.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import config

CATALOG_VERSION = "avicenna-catalog/1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trials (
  trial_id        TEXT PRIMARY KEY,
  registry        TEXT NOT NULL,
  title           TEXT,
  short_title     TEXT,
  status          TEXT,
  status_detail   TEXT,
  available       INTEGER NOT NULL,
  recruiting      INTEGER,
  phase           TEXT,
  study_type      TEXT,
  conditions_json TEXT NOT NULL,
  sex             TEXT,
  min_age_years   REAL,
  max_age_years   REAL,
  age_groups      TEXT,
  sites_json      TEXT NOT NULL,
  geo_rank        INTEGER NOT NULL,
  best_site       TEXT,
  inclusion_json  TEXT NOT NULL,
  exclusion_json  TEXT NOT NULL,
  products        TEXT,
  sponsor         TEXT,
  linked_ids_json TEXT NOT NULL,
  url             TEXT,
  last_update     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trials_available ON trials(available);
CREATE INDEX IF NOT EXISTS idx_trials_geo ON trials(geo_rank);
CREATE VIRTUAL TABLE IF NOT EXISTS trials_fts USING fts5(
  trial_id UNINDEXED, title, conditions, eligibility, extra,
  tokenize = 'unicode61 remove_diacritics 2'
);
"""

GEO_LABELS = {
    1: "FN Motol / Homolka (Prague)",
    2: "Prague (other site)",
    3: "Brno / Ostrava",
    4: "Czechia (other city)",
    5: "outside Czechia / unknown",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def fold(text: Optional[str]) -> str:
    """Lowercase + strip diacritics (for site/city matching)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _loads(s: Optional[str], default):
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def site_rank(site: Dict[str, Any]) -> int:
    org, city, country = fold(site.get("org")), fold(site.get("city")), fold(site.get("country"))
    if country not in ("czechia", "czech republic", "cz", ""):
        return 5
    if "motol" in org or "homolka" in org or "motol" in city:
        return 1
    if "praha" in city or "prague" in city or "praha" in org or "prague" in org:
        return 2
    if "brno" in city or "ostrava" in city:
        return 3
    if country:
        return 4
    return 5


def geo_rank(sites: Iterable[Dict[str, Any]]) -> Tuple[int, Optional[str]]:
    best, best_site = 5, None
    for s in sites:
        r = site_rank(s)
        if r < best:
            best = r
            best_site = ", ".join(x for x in (s.get("org"), s.get("city")) if x)
    return best, best_site


_AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(year|month|week|day)s?\s*$", re.I)
_AGE_DIV = {"year": 1.0, "month": 12.0, "week": 52.1775, "day": 365.25}


def parse_ctgov_age(raw: Optional[str]) -> Optional[float]:
    """'18 Years' → 18.0; '6 Months' → 0.5. Unparseable/N/A → None (never guessed)."""
    if not raw:
        return None
    m = _AGE_RE.match(raw)
    if not m:
        return None
    return round(float(m.group(1)) / _AGE_DIV[m.group(2).lower()], 4)


_CTIS_AGE_BANDS = {"in utero": (0.0, 0.0), "0-17 years": (0.0, 17.0), "18-64 years": (18.0, 64.0),
                   "65+ years": (65.0, None)}


def parse_ctis_age_groups(raw: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """CTIS population age groups → covering [min, max] years (max None = open). Unknown token → (None, None)."""
    if not raw:
        return None, None
    lo, hi, any_open = None, None, False
    for tok in (t.strip().lower() for t in raw.split(",") if t.strip()):
        if tok not in _CTIS_AGE_BANDS:
            return None, None
        a, b = _CTIS_AGE_BANDS[tok]
        lo = a if lo is None else min(lo, a)
        if b is None:
            any_open = True
        else:
            hi = b if hi is None else max(hi, b)
    return lo, (None if any_open else hi)


_HEADER_RE = re.compile(r"^\s*(?:key\s+|main\s+|principal\s+)?(inclusion|exclusion)\s+criteria\b.*$", re.I)
_BULLET_RE = re.compile(r"^(\s*)(?:[*\-•·]|\d{1,2}[.)]|[a-z][.)])\s+(.*)$", re.I)


def split_eligibility_text(text: Optional[str]) -> Tuple[List[str], List[str]]:
    """Split a CT.gov eligibility blob into verbatim inclusion / exclusion bullets.

    Top-level bullets start a new item; indented sub-bullets and wrapped lines are appended to the
    current item so that each item stays a self-contained criterion. Text before any header is
    treated as inclusion context. Nothing is paraphrased.
    """
    inc: List[str] = []
    exc: List[str] = []
    if not text:
        return inc, exc
    section = inc
    current: Optional[List[str]] = None
    base_indent: Optional[int] = None

    def flush():
        nonlocal current
        if current:
            item = " ".join(p.strip() for p in current if p.strip())
            if item:
                section.append(item)
        current = None

    for line in text.splitlines():
        if not line.strip():
            continue
        h = _HEADER_RE.match(line)
        if h:
            flush()
            section = inc if h.group(1).lower() == "inclusion" else exc
            base_indent = None
            continue
        m = _BULLET_RE.match(line)
        if m:
            indent = len(m.group(1).expandtabs(4))
            if base_indent is None:
                base_indent = indent
            if indent <= base_indent or current is None:
                flush()
                current = [m.group(2)]
            else:
                current.append(m.group(2))
            continue
        if current is None:
            current = [line]
        else:
            current.append(line)
    flush()
    return inc, exc


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def _ctgov_rows(path: Path) -> Iterable[Dict[str, Any]]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT nct_id, brief_title, official_title, overall_status, conditions_json, phase_json,"
            " eligibility_text, sex, min_age, max_age, locations_json, eu_ct_ids_json,"
            " json_extract(study_json, '$.protocolSection.designModule.studyType'),"
            " json_extract(study_json, '$.protocolSection.statusModule.lastUpdatePostDateStruct.date'),"
            " json_extract(study_json, '$.protocolSection.sponsorCollaboratorsModule.leadSponsor.name'),"
            " json_extract(study_json, '$.protocolSection.armsInterventionsModule.interventions')"
            " FROM ctgov_studies")
        for (nct, brief, official, status, cond, phase, elig, sex, min_age, max_age, locs, euids,
             stype, updated, sponsor, interventions) in cur:
            locations = _loads(locs, [])
            sites = [{"org": l.get("facility"), "city": l.get("city"), "country": l.get("country"),
                      "status": l.get("status")} for l in locations]
            cz_sites = [s for s in sites if fold(s["country"]) in ("czechia", "czech republic")]
            rank, best = geo_rank(sites)
            inc, exc = split_eligibility_text(elig)
            st = (status or "").upper()
            recruiting = 1 if st == "RECRUITING" else 0
            available = 1 if st in ("RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION") else 0
            cz_rec = [s for s in cz_sites if (s.get("status") or "").upper() == "RECRUITING"]
            detail = st.replace("_", " ").lower()
            if cz_sites:
                detail += f"; {len(cz_rec)}/{len(cz_sites)} Czech site(s) recruiting"
            products = ", ".join(sorted({i.get("name") for i in (_loads(interventions, []) or []) if i.get("name")}))
            sex_n = {"ALL": "all", "FEMALE": "female", "MALE": "male"}.get((sex or "").upper())
            yield {
                "trial_id": nct, "registry": "ctgov", "title": official or brief, "short_title": brief,
                "status": status, "status_detail": detail, "available": available, "recruiting": recruiting,
                "phase": ", ".join(_loads(phase, []) or []) or None,
                "study_type": (stype or "").lower() or None,
                "conditions": _loads(cond, []) or [], "sex": sex_n,
                "min_age_years": parse_ctgov_age(min_age), "max_age_years": parse_ctgov_age(max_age),
                "age_groups": None, "sites": sites, "geo_rank": rank, "best_site": best,
                "inclusion": inc, "exclusion": exc, "products": products or None, "sponsor": sponsor,
                "linked_ids": _loads(euids, []) or [],
                "url": f"https://clinicaltrials.gov/study/{nct}", "last_update": updated,
            }
    finally:
        con.close()


def _ctis_rows(path: Path) -> Iterable[Dict[str, Any]]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        cz = {}
        for ct, ts, started in con.execute(
                "SELECT r.ct_number, json_extract(p.value, '$.mscInfo.trialStatus'),"
                " json_extract(p.value, '$.mscInfo.hasRecruitmentStarted')"
                " FROM trials_retrieve r, json_each(r.retrieve_json, '$.authorizedApplication.authorizedPartsII') p"
                " WHERE json_extract(p.value, '$.mscInfo.mscName') = 'Czechia'"):
            cz[ct] = (ts, started)
        cur = con.execute(
            "SELECT r.ct_number, r.status, r.public_title, r.short_title, r.conditions_json, r.inclusions_json,"
            " r.exclusions_json, r.sites_json, s.title, s.trial_phase, s.age_group, s.gender, s.product,"
            " s.sponsor, s.medical_conditions, s.ct_status_code,"
            " json_extract(s.overview_json, '$.lastUpdated'),"
            " json_extract(r.retrieve_json, '$.authorizedApplication.authorizedPartI.trialDetails"
            ".clinicalTrialIdentifiers.secondaryIdentifyingNumbers.nctNumber.number')"
            " FROM trials_retrieve r LEFT JOIN trials_search s USING (ct_number)")
        for (ct, status, public_title, short, cond, incs, excs, sites_j, s_title, phase, age_group, gender,
             product, sponsor, med_cond, code, updated, nct) in cur:
            sites = [{"org": s.get("org"), "city": s.get("city"), "country": s.get("country")}
                     for s in (_loads(sites_j, []) or [])]
            rank, best = geo_rank(sites)
            cz_status, cz_started = cz.get(ct, (None, None))
            authorised = (cz_status or status) == "Authorised"
            available = 1 if authorised else 0
            recruiting = (1 if cz_started else 0) if authorised else 0
            if cz_status:
                detail = f"CZ: {cz_status}" + (
                    ("; recruitment started in CZ" if cz_started else "; recruitment not yet started in CZ")
                    if authorised else "")
            else:
                detail = status or ""
            if code is not None:
                detail += f" (CTIS public status code {code})"
            g = {x.strip().lower() for x in (gender or "").split(",") if x.strip()}
            sex = "all" if g == {"female", "male"} else "female" if g == {"female"} else \
                "male" if g == {"male"} else None
            lo, hi = parse_ctis_age_groups(age_group)
            conditions = _loads(cond, []) or ([med_cond] if med_cond else [])
            yield {
                "trial_id": ct, "registry": "ctis", "title": public_title or s_title, "short_title": short,
                "status": status, "status_detail": detail, "available": available, "recruiting": recruiting,
                "phase": phase, "study_type": "interventional",
                "conditions": conditions, "sex": sex, "min_age_years": lo, "max_age_years": hi,
                "age_groups": age_group, "sites": sites, "geo_rank": rank, "best_site": best,
                "inclusion": _loads(incs, []) or [], "exclusion": _loads(excs, []) or [],
                "products": product, "sponsor": sponsor,
                "linked_ids": [nct.strip()] if isinstance(nct, str) and nct.strip().upper().startswith("NCT") else [],
                "url": f"https://euclinicaltrials.eu/search-for-clinical-trials/?lang=en&EUCT={ct}",
                "last_update": updated,
            }
    finally:
        con.close()


def build_catalog(out: Optional[Path] = None, *, ctgov: Optional[Path] = None,
                  ctis: Optional[Path] = None) -> Dict[str, Any]:
    """(Re)build the catalog from whichever source databases exist. Returns build stats."""
    out = out or config.catalog_db()
    ctgov = ctgov or config.ctgov_db()
    ctis = ctis or config.ctis_db()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript(_SCHEMA)
    counts = {"ctgov": 0, "ctis": 0}
    sources = []
    for name, path, rows in (("ctgov", ctgov, _ctgov_rows), ("ctis", ctis, _ctis_rows)):
        if not path.exists():
            continue
        sources.append(f"{name}={path}@{int(path.stat().st_mtime)}")
        for r in rows(path):
            _insert(con, r)
            counts[name] += 1
    # Each registry may name the other's id (CT.gov → EU CT number, CTIS → NCT); make links symmetric.
    for tid, linked in con.execute("SELECT trial_id, linked_ids_json FROM trials").fetchall():
        for other in json.loads(linked):
            row = con.execute("SELECT linked_ids_json FROM trials WHERE trial_id=?", (other,)).fetchone()
            if row:
                ids = sorted(set(json.loads(row[0])) | {tid})
                con.execute("UPDATE trials SET linked_ids_json=? WHERE trial_id=?", (json.dumps(ids), other))
    meta = {"catalog_version": CATALOG_VERSION, "sources": ";".join(sources),
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count_ctgov": str(counts["ctgov"]), "count_ctis": str(counts["ctis"])}
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", meta.items())
    con.commit()
    con.close()
    tmp.replace(out)
    return {"catalog": str(out), **meta}


def _insert(con: sqlite3.Connection, r: Dict[str, Any]) -> None:
    con.execute(
        "INSERT OR REPLACE INTO trials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (r["trial_id"], r["registry"], r["title"], r["short_title"], r["status"], r["status_detail"],
         r["available"], r["recruiting"], r["phase"], r["study_type"], json.dumps(r["conditions"], ensure_ascii=False),
         r["sex"], r["min_age_years"], r["max_age_years"], r["age_groups"],
         json.dumps(r["sites"], ensure_ascii=False), r["geo_rank"], r["best_site"],
         json.dumps(r["inclusion"], ensure_ascii=False), json.dumps(r["exclusion"], ensure_ascii=False),
         r["products"], r["sponsor"], json.dumps(r["linked_ids"]), r["url"], r["last_update"]))
    con.execute("DELETE FROM trials_fts WHERE trial_id=?", (r["trial_id"],))
    con.execute(
        "INSERT INTO trials_fts (trial_id, title, conditions, eligibility, extra) VALUES (?,?,?,?,?)",
        (r["trial_id"], " ".join(x for x in (r["title"], r["short_title"]) if x),
         " ".join(r["conditions"]), " ".join(r["inclusion"] + r["exclusion"]),
         " ".join(x for x in (r["products"], r["sponsor"], r["phase"], r["trial_id"]) if x)))


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def fts_query(text: str, mode: str = "and") -> Optional[str]:
    """Free text → safe FTS5 expression (quoted prefix tokens). None if no usable token."""
    toks = [t for t in _TOKEN_RE.findall(text or "") if len(t) > 1 or t.isdigit()]
    if not toks:
        return None
    joiner = " AND " if mode == "and" else " OR "
    return joiner.join(f'"{t}"*' for t in toks)


class TrialCatalog:
    """Read access to the catalog. Builds it on first use if absent or older than its sources."""

    def __init__(self, path: Optional[Path] = None, *, auto_build: bool = True):
        self.path = path or config.catalog_db()
        if auto_build and self._stale():
            build_catalog(self.path)
        if not self.path.exists():
            raise FileNotFoundError(f"trial catalog not found: {self.path}")
        self.con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    def _stale(self) -> bool:
        if not self.path.exists():
            return True
        built = self.path.stat().st_mtime
        return any(p.exists() and p.stat().st_mtime > built for p in (config.ctgov_db(), config.ctis_db()))

    def close(self) -> None:
        self.con.close()

    def meta(self) -> Dict[str, str]:
        return {k: v for k, v in self.con.execute("SELECT key, value FROM meta")}

    def search(
        self,
        query: Optional[str] = None,
        *,
        available_only: bool = True,
        recruiting_only: bool = False,
        registry: Optional[str] = None,
        max_geo_rank: Optional[int] = None,
        phase: Optional[str] = None,
        patient_age: Optional[float] = None,
        patient_sex: Optional[str] = None,
        sort: str = "geo",
        limit: int = 20,
        offset: int = 0,
        dedupe_linked: bool = True,
        mode: str = "auto",
    ) -> Dict[str, Any]:
        """Search the catalog. Returns {"total", "results": [summary...], "query_used"}.

        Query semantics (`mode`): "and" = all words must match, "or" = any word, "auto" = "and" falling
        back to "or" when nothing matches. Prefix match, diacritics-insensitive; `query_used.mode`
        reports what was applied.
        """
        where, params = [], []
        if available_only:
            where.append("t.available = 1")
        if recruiting_only:
            where.append("t.recruiting = 1")
        if registry:
            where.append("t.registry = ?")
            params.append(registry)
        if max_geo_rank:
            where.append("t.geo_rank <= ?")
            params.append(int(max_geo_rank))
        if phase:
            where.append("lower(coalesce(t.phase,'')) LIKE ?")
            params.append(f"%{phase.lower()}%")
        if patient_age is not None:
            where.append("(t.min_age_years IS NULL OR t.min_age_years <= ?)")
            where.append("(t.max_age_years IS NULL OR t.max_age_years >= ?)")
            params += [patient_age, patient_age]
        if patient_sex in ("female", "male"):
            where.append("(t.sex IS NULL OR t.sex IN ('all', ?))")
            params.append(patient_sex)

        order_geo = "t.geo_rank ASC, rank ASC, t.trial_id ASC"
        order_rel = "rank ASC, t.geo_rank ASC, t.trial_id ASC"
        mode_used = None
        rows: List[sqlite3.Row] = []
        modes = {"auto": ("and", "or"), "and": ("and",), "or": ("or",)}[mode]
        for m in modes if query else (None,):
            q = fts_query(query, m) if query else None
            if query and q is None:
                break
            sql = ["SELECT t.*, " + ("bm25(trials_fts, 0, 10.0, 8.0, 1.0, 2.0)" if q else "0.0") + " AS rank FROM trials t"]
            p = list(params)
            if q:
                sql.append("JOIN trials_fts f ON f.trial_id = t.trial_id")
                w = ["trials_fts MATCH ?"] + where
                p = [q] + p
            else:
                w = where
            if w:
                sql.append("WHERE " + " AND ".join(w))
            sql.append("ORDER BY " + (order_rel if sort == "relevance" else order_geo))
            rows = self.con.execute(" ".join(sql), p).fetchall()
            mode_used = m
            if rows:
                break

        if dedupe_linked:
            present = {r["trial_id"] for r in rows}
            rows = [r for r in rows
                    if not (r["registry"] == "ctis" and any(l in present for l in json.loads(r["linked_ids_json"])))]
        total = len(rows)
        page = rows[offset: offset + limit]
        return {
            "total": total,
            "query_used": {"text": query, "mode": mode_used, "available_only": available_only,
                           "recruiting_only": recruiting_only, "max_geo_rank": max_geo_rank, "sort": sort},
            "results": [self._summary(r) for r in page],
        }

    def get(self, trial_id: str) -> Optional[Dict[str, Any]]:
        r = self.con.execute("SELECT *, 0.0 AS rank FROM trials WHERE trial_id = ?", (trial_id,)).fetchone()
        if r is None:
            return None
        d = self._summary(r)
        d.update({
            "sites": json.loads(r["sites_json"]),
            "inclusion_criteria": json.loads(r["inclusion_json"]),
            "exclusion_criteria": json.loads(r["exclusion_json"]),
            "sponsor": r["sponsor"], "products": r["products"], "last_update": r["last_update"],
        })
        return d

    def get_many(self, trial_ids: Iterable[str]) -> List[Dict[str, Any]]:
        return [t for t in (self.get(i) for i in trial_ids) if t is not None]

    @staticmethod
    def _summary(r: sqlite3.Row) -> Dict[str, Any]:
        return {
            "trial_id": r["trial_id"], "registry": r["registry"], "title": r["title"],
            "short_title": r["short_title"], "status": r["status"], "status_detail": r["status_detail"],
            "available": bool(r["available"]), "recruiting": None if r["recruiting"] is None else bool(r["recruiting"]),
            "phase": r["phase"], "study_type": r["study_type"], "conditions": json.loads(r["conditions_json"]),
            "sex": r["sex"], "min_age_years": r["min_age_years"], "max_age_years": r["max_age_years"],
            "age_groups": r["age_groups"], "geo_rank": r["geo_rank"], "geo_label": GEO_LABELS[r["geo_rank"]],
            "best_site": r["best_site"], "linked_ids": json.loads(r["linked_ids_json"]), "url": r["url"],
            "n_inclusion": len(json.loads(r["inclusion_json"])), "n_exclusion": len(json.loads(r["exclusion_json"])),
        }
