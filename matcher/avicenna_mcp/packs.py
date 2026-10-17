"""CriteriaPack sources: curated packs on disk, else a pack derived from registry fields.

Curated packs (`matcher/packs/<trial_id>.json`) are atomized by a curator or an LLM following the
`trial-data-format` skill and validated before they are stored. They take precedence.

Registry packs are built mechanically and conservatively for every catalog trial without one:
- structured age limits → evaluable hard inclusions (`complete`);
- structured sex restriction → hard inclusion marked `partial`: registry *sex* and the packet's
  *administrative gender* are different concepts, so the atom may only ever satisfy the criterion,
  never disqualify (PATIENT_MATCHING_FORMAT_STANDARD §262). The probability layer flags mismatches;
- every eligibility bullet → its own verbatim `opaque_text` criterion (consent / willingness /
  investigator-judgment bullets → `procedural_pre_screen`), nothing is interpreted;
- `criteria_completeness = "partial"` always (best state is therefore `needs_chart_review`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from avicenna_matcher.errors import StructuralError
from avicenna_matcher.pipeline import dependency_order
from avicenna_matcher.validator import validate

from . import config

REGISTRY_PACK_VERSION = "avicenna-registry-pack/0.1"
AUTO_GENERATED_AT = "2026-01-01T00:00:00Z"  # fixed: registry packs are a pure function of the catalog row

_PROCEDURAL_RE = re.compile(
    r"informed consent|consent form|\bwilling\b|\bwillingness\b|able (?:and willing )?to comply|"
    r"\bable to (?:understand|provide|give)|in the (?:opinion|judgment|judgement) of the investigator|"
    r"investigator'?s? (?:opinion|judgment|judgement)|compliance with (?:the )?(?:study|protocol)",
    re.I)

SEX_CRITERION_ID = "inc:registry-sex"
MIN_AGE_CRITERION_ID = "inc:registry-min-age"
MAX_AGE_CRITERION_ID = "inc:registry-max-age"
UNPUBLISHED_CRITERION_ID = "inc:registry-unpublished"
GENDER_SYSTEM = "http://hl7.org/fhir/administrative-gender"


def _safe_name(trial_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", trial_id or ""):
        raise ValueError(f"unsafe trial_id for a file name: {trial_id!r}")
    return trial_id


def _criterion(cid: str, ctype: str, src: str, atoms: List[dict], note: str, hardness: str = "hard") -> dict:
    return {"criterion_id": cid, "criterion_type": ctype, "hardness": hardness, "arm_scope": None,
            "source_text": src, "atoms": atoms, "completeness_note": note}


def _age_atom(aid: str, src: str, comparator: str, years: float) -> dict:
    v = int(years) if float(years).is_integer() else years
    return {"atom_id": aid, "predicate_type": "simple_comparison", "arm_scope": None, "source_text": src,
            "fact_key": "demographics.age", "comparator": comparator, "threshold": {"value": v, "unit": "a"}}


def registry_pack(trial: Dict[str, Any]) -> dict:
    """Build a conservative CriteriaPack from a catalog trial record (see module docstring)."""
    tid = trial["trial_id"]
    criteria: List[dict] = []
    # CT.gov min/max age are eligibility limits. CTIS only declares the *population age groups*
    # (e.g. "18-64 years"), which are indicative, so those may satisfy but never disqualify.
    is_ctis = trial.get("registry") == "ctis"
    src_kind = "CTIS declared population age groups" if is_ctis else "registry structured field"
    age_note = "partial" if is_ctis else "complete"
    lo, hi = trial.get("min_age_years"), trial.get("max_age_years")
    if lo is not None and lo > 0:
        src = f"Minimum age: {lo:g} years ({src_kind})"
        criteria.append(_criterion(MIN_AGE_CRITERION_ID, "inclusion", src, [_age_atom("a", src, "ge", lo)],
                                   age_note))
    if hi is not None:
        src = f"Maximum age: {hi:g} years ({src_kind})"
        criteria.append(_criterion(MAX_AGE_CRITERION_ID, "inclusion", src, [_age_atom("a", src, "le", hi)],
                                   age_note))
    sex = trial.get("sex")
    if sex in ("female", "male"):
        src = f"Sex: {sex} only (registry structured field)"
        atom = {"atom_id": "s", "predicate_type": "simple_comparison", "arm_scope": None, "source_text": src,
                "fact_key": "demographics.administrative_gender", "comparator": "eq",
                "threshold": {"system": GENDER_SYSTEM, "code": sex},
                }
        criteria.append(_criterion(SEX_CRITERION_ID, "inclusion", src, [atom], "partial"))
    for kind, prefix, items in (("inclusion", "inc", trial.get("inclusion_criteria") or []),
                                ("exclusion", "exc", trial.get("exclusion_criteria") or [])):
        for i, text in enumerate(items, 1):
            hardness = "procedural_pre_screen" if _PROCEDURAL_RE.search(text) else "hard"
            criteria.append(_criterion(f"{prefix}:registry-{i}", kind, text, [], "opaque_text", hardness))
    if not (trial.get("inclusion_criteria") or trial.get("exclusion_criteria")):
        criteria.append(_criterion(UNPUBLISHED_CRITERION_ID, "inclusion",
                                   "Eligibility criteria not available in the local registry snapshot.", [],
                                   "opaque_text"))
    study_type = trial.get("study_type") or "interventional"
    if study_type not in ("interventional", "observational"):
        study_type = "interventional"
    pack = {
        "schema_version": "avicenna.criteria-pack/0.1",
        "pack_id": f"{tid}@{trial.get('last_update') or 'unknown'}/{REGISTRY_PACK_VERSION}",
        "trial_id": tid,
        "criteria_completeness": "partial",
        "generated_at": AUTO_GENERATED_AT,
        "arms": [{"arm_id": "main", "arm_name": "All participants (registry-derived)", "study_type": study_type}],
        "criteria": criteria,
    }
    validate(pack, "criteria_pack")
    return pack


def check_pack(pack: dict) -> List[str]:
    """Structural checks beyond the JSON schema. Raises StructuralError; returns warnings."""
    validate(pack, "criteria_pack")
    dependency_order(pack["criteria"])
    warnings = []
    arm_ids = {a["arm_id"] for a in pack["arms"]}
    for c in pack["criteria"]:
        if c["arm_scope"] is not None and c["arm_scope"] not in arm_ids:
            raise StructuralError(f"{c['criterion_id']}: arm_scope {c['arm_scope']!r} is not an arm")
        non_gate = [a for a in c["atoms"] if a["predicate_type"] != "applicability_gate"]
        if len(non_gate) > 1 and not c.get("logic"):
            warnings.append(f"{c['criterion_id']}: >1 atom without logic → always unresolved (logic_unspecified)")
        if c["completeness_note"] == "opaque_text" and c["atoms"]:
            warnings.append(f"{c['criterion_id']}: opaque_text criterion carries atoms")
        if c["completeness_note"] != "opaque_text" and not c["atoms"]:
            warnings.append(f"{c['criterion_id']}: no atoms but completeness_note={c['completeness_note']}")
        for a in c["atoms"]:
            if a.get("fact_key") in ("biomarker.result", "lab.result") and not a.get("concept"):
                warnings.append(f"{c['criterion_id']}/{a['atom_id']}: {a['fact_key']} atom without concept "
                                "→ always unresolved (concept_unspecified)")
    return warnings


class PackStore:
    """Curated packs on disk, one `<trial_id>.json` per trial."""

    def __init__(self, directory: Optional[Path] = None):
        self.dir = directory or config.packs_dir()

    def path_for(self, trial_id: str) -> Path:
        return self.dir / f"{_safe_name(trial_id)}.json"

    def get(self, trial_id: str) -> Optional[dict]:
        try:
            p = self.path_for(trial_id)
        except ValueError:
            return None
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def list(self) -> List[Dict[str, Any]]:
        out = []
        if not self.dir.exists():
            return out
        for p in sorted(self.dir.glob("*.json")):
            try:
                pk = json.loads(p.read_text(encoding="utf-8"))
                out.append({"trial_id": pk.get("trial_id"), "pack_id": pk.get("pack_id"),
                            "criteria_completeness": pk.get("criteria_completeness"),
                            "n_criteria": len(pk.get("criteria") or [])})
            except (OSError, ValueError):
                out.append({"file": p.name, "error": "unreadable"})
        return out

    def save(self, pack: dict, *, overwrite: bool = False) -> Tuple[Path, List[str]]:
        warnings = check_pack(pack)
        p = self.path_for(pack["trial_id"])
        if p.exists() and not overwrite:
            raise FileExistsError(f"a curated pack for {pack['trial_id']} exists; pass overwrite=true to replace")
        self.dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return p, warnings


def resolve_pack(trial: Optional[Dict[str, Any]], trial_id: str, store: PackStore) -> Tuple[Optional[dict], str]:
    """Return (pack, source) where source ∈ {'curated', 'curated_linked', 'registry', 'none'}."""
    pk = store.get(trial_id)
    if pk is not None:
        return pk, "curated"
    for other in (trial or {}).get("linked_ids") or []:
        pk = store.get(other)
        if pk is not None:
            return pk, "curated_linked"
    if trial is None:
        return None, "none"
    return registry_pack(trial), "registry"
