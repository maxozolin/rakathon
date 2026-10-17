#!/usr/bin/env python3
"""Deterministic Trial CriteriaPack builder.

Turns the local trial catalog (data/catalog/trial_catalog.sqlite) into
schema-valid ``avicenna.criteria-pack/0.1`` JSON packs, one per trial, written
to ``matcher/packs/``.

This is a *fail-closed, deterministic* pass that follows the safety philosophy
of ``prompts/TRIAL_PACK_BUILDER_PROMPT.md``: a wrong atom is worse than an
opaque one. It only encodes atoms it can derive without guessing:

* structured minimum/maximum age -> ``demographics.age`` comparisons;
* structured single-sex restriction -> ``demographics.administrative_gender``;

every free-text eligibility bullet is kept verbatim as an **opaque** criterion
with the correct inclusion/exclusion polarity. Judgment / consent / willingness
bullets are marked ``procedural_pre_screen``. ``criteria_completeness`` is
``partial`` because the free text is not fully atomized here (an LLM atomizer
per the prompt can later enrich these packs in place).

Usage::

    python matcher/tools/build_catalog_packs.py            # all available trials
    python matcher/tools/build_catalog_packs.py --all      # every catalog row
    python matcher/tools/build_catalog_packs.py --limit 20 # pilot
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATCHER = ROOT / "matcher"
sys.path.insert(0, str(MATCHER))

from avicenna_matcher.validator import validate  # noqa: E402
from avicenna_matcher.errors import ValidationError  # noqa: E402

CATALOG = ROOT / "data" / "catalog" / "trial_catalog.sqlite"
OUT_DIR = MATCHER / "packs"
BUILDER_VERSION = "trial-pack-builder-deterministic/1.0.0"

# Bullets that are pure procedural pre-screen (judgment / consent / compliance).
_PROCEDURAL_RE = re.compile(
    r"informed consent|in the (?:opinion|judg?ment) of the investigator"
    r"|investigator'?s (?:assessment|opinion|judg?ement|discretion)"
    r"|willing(?:ness)? (?:and able |to )|able to (?:comply|adhere|understand)"
    r"|able and willing|lifestyle restrictions|sign(?:ed|s)? (?:an |the )?(?:icf|informed)",
    re.IGNORECASE,
)

# Rendering artifacts (private-use bullet glyphs) to strip from the edges.
_BULLET_CHARS = "\uf0b7\u2022\u00b7\u25cf\u25aa-\u2013\u2014 \t"


def _slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = "-".join(slug.split("-")[:6])
    return slug or fallback


def _clean(text: str) -> str:
    """Trim whitespace and leading bullet glyphs; keep inner text verbatim."""
    return text.strip().strip(_BULLET_CHARS).strip()


def _study_type(raw: str | None) -> str:
    if raw == "observational":
        return "observational"
    return "interventional"


def _gender_code(sex: str | None) -> dict | None:
    if sex == "male":
        return {"system": "http://hl7.org/fhir/administrative-gender", "code": "male"}
    if sex == "female":
        return {"system": "http://hl7.org/fhir/administrative-gender", "code": "female"}
    return None


def _criterion(cid, ctype, text, atoms, *, hardness="hard", logic=None, note="opaque_text"):
    crit = {
        "criterion_id": cid,
        "criterion_type": ctype,
        "hardness": hardness,
        "arm_scope": None,
        "source_text": text,
        "atoms": atoms,
        "completeness_note": note,
    }
    if logic is not None:
        crit["logic"] = {"op": logic, "notes": None}
    return crit


def build_pack(row: sqlite3.Row, generated_at: str) -> dict:
    trial_id = row["trial_id"]
    last_update = (row["last_update"] or "unknown").strip() or "unknown"
    criteria: list[dict] = []
    used_ids: set[str] = set()

    def add(cid: str, *args, **kwargs):
        base = cid
        n = 2
        while cid in used_ids:
            cid = f"{base}-{n}"
            n += 1
        used_ids.add(cid)
        criteria.append(_criterion(cid, *args, **kwargs))

    # --- structured demographics -> real atoms -------------------------------
    min_age = row["min_age_years"]
    if min_age is not None:
        add(
            "inc:age-min",
            "inclusion",
            f"Minimum age: {min_age:g} years (registry structured field)",
            [
                {
                    "atom_id": "a",
                    "predicate_type": "simple_comparison",
                    "arm_scope": None,
                    "source_text": f"Age \u2265 {min_age:g} years",
                    "fact_key": "demographics.age",
                    "comparator": "ge",
                    "threshold": {"value": float(min_age), "unit": "a"},
                }
            ],
            note="complete",
        )

    max_age = row["max_age_years"]
    if max_age is not None:
        add(
            "inc:age-max",
            "inclusion",
            f"Maximum age: {max_age:g} years (registry structured field)",
            [
                {
                    "atom_id": "a",
                    "predicate_type": "simple_comparison",
                    "arm_scope": None,
                    "source_text": f"Age \u2264 {max_age:g} years",
                    "fact_key": "demographics.age",
                    "comparator": "le",
                    "threshold": {"value": float(max_age), "unit": "a"},
                }
            ],
            note="complete",
        )

    gender = _gender_code(row["sex"])
    if gender is not None:
        add(
            "inc:sex",
            "inclusion",
            f"Sex eligible for study: {row['sex']} (registry structured field)",
            [
                {
                    "atom_id": "a",
                    "predicate_type": "simple_comparison",
                    "arm_scope": None,
                    "source_text": f"Sex: {row['sex']}",
                    "fact_key": "demographics.administrative_gender",
                    "comparator": "eq",
                    "threshold": gender,
                }
            ],
            note="complete",
        )

    # --- free-text eligibility bullets -> verbatim opaque criteria -----------
    def add_bullets(raw_json: str, ctype: str, prefix: str):
        try:
            bullets = json.loads(raw_json) if raw_json else []
        except (json.JSONDecodeError, TypeError):
            bullets = []
        idx = 0
        for bullet in bullets:
            if not isinstance(bullet, str):
                continue
            text = _clean(bullet)
            if not text:
                continue
            idx += 1
            hardness = (
                "procedural_pre_screen" if _PROCEDURAL_RE.search(text) else "hard"
            )
            slug = _slugify(text, f"b{idx}")
            add(f"{prefix}:{slug}", ctype, text, [], hardness=hardness)

    add_bullets(row["inclusion_json"], "inclusion", "inc")
    add_bullets(row["exclusion_json"], "exclusion", "exc")

    pack = {
        "schema_version": "avicenna.criteria-pack/0.1",
        "pack_id": f"{trial_id}@{last_update}/{BUILDER_VERSION}",
        "trial_id": trial_id,
        "criteria_completeness": "partial",
        "generated_at": generated_at,
        "arms": [
            {
                "arm_id": "main",
                "arm_name": "All participants",
                "study_type": _study_type(row["study_type"]),
            }
        ],
        "criteria": criteria,
    }
    return pack


def _safe_filename(trial_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", trial_id) + ".json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="include non-available trials")
    ap.add_argument("--limit", type=int, default=None, help="cap number of trials")
    ap.add_argument(
        "--out", type=Path, default=OUT_DIR, help="output directory for packs"
    )
    args = ap.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = (
        _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    ).replace("+00:00", "Z")

    conn = sqlite3.connect(f"file:{CATALOG}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    where = "" if args.all else "WHERE available = 1"
    limit = f" LIMIT {int(args.limit)}" if args.limit else ""
    rows = conn.execute(
        f"SELECT * FROM trials {where} ORDER BY geo_rank, trial_id{limit}"
    ).fetchall()
    conn.close()

    written = 0
    failures: list[tuple[str, str]] = []
    index: list[dict] = []
    for row in rows:
        try:
            pack = build_pack(row, generated_at)
            validate(pack, "criteria_pack")
        except ValidationError as exc:
            failures.append((row["trial_id"], str(exc)))
            continue
        except Exception as exc:  # pragma: no cover - defensive
            failures.append((row["trial_id"], f"{type(exc).__name__}: {exc}"))
            continue
        path = out_dir / _safe_filename(row["trial_id"])
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(pack, fh, ensure_ascii=False, indent=2)
        written += 1
        index.append(
            {
                "trial_id": row["trial_id"],
                "registry": row["registry"],
                "file": path.name,
                "n_criteria": len(pack["criteria"]),
                "geo_rank": row["geo_rank"],
            }
        )

    with open(out_dir / "catalog_packs_index.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "generated_at": generated_at,
                "builder": BUILDER_VERSION,
                "source_catalog": str(CATALOG.relative_to(ROOT)),
                "written": written,
                "failed": len(failures),
                "packs": index,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )

    print(f"candidates : {len(rows)}")
    print(f"written    : {written}")
    print(f"failed     : {len(failures)}")
    for tid, err in failures[:20]:
        print(f"  FAIL {tid}: {err[:140]}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
