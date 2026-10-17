"""Search → evaluate → split into `excluded` and `can_apply`, with a probability per candidate."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from avicenna_matcher import pipeline
from avicenna_matcher.adapter import CANONICAL_VERSION, adapt, check_authorization_policy
from avicenna_matcher.validator import validate, validate_packet_facts
from avicenna_matcher.cli import derive_result_id
from avicenna_matcher.errors import StructuralError

from .catalog import TrialCatalog
from .packs import PackStore, resolve_pack
from .patient import patient_profile
from .probability import DISCLAIMER, estimate

STATE_ORDER = {"eligible_pending_review": 0, "needs_chart_review": 1, "manual_review": 2, "ineligible": 3}
STATE_MEANING = {
    "eligible_pending_review": "every hard criterion is satisfied from the record; confirm at screening",
    "needs_chart_review": "nothing rules the patient out, but some criteria need data from the chart",
    "manual_review": "nothing rules the patient out, but key criteria are free text a human must read",
    "ineligible": "at least one hard criterion is resolved against the patient",
}


def load_packet(packet: Optional[Dict[str, Any]] = None, packet_path: Optional[str] = None) -> Dict[str, Any]:
    if (packet is None) == (packet_path is None):
        raise ValueError("provide exactly one of `packet` (object) or `packet_path` (local JSON file)")
    if packet_path is not None:
        with open(Path(packet_path).expanduser(), encoding="utf-8") as f:
            packet = json.load(f)
    if not isinstance(packet, dict):
        raise ValueError("patient packet must be a JSON object")
    return packet


def check_packet(packet: dict, context: Optional[dict] = None) -> Dict[str, Any]:
    """Validate a canonical (1.1.0) or internal packet exactly as the matcher will. Raises StructuralError."""
    auth = check_authorization_policy((context or {}).get("authorization_policy"))
    losses: List[dict] = []
    internal = packet
    if packet.get("schema_version") == CANONICAL_VERSION:
        internal, report = adapt(copy.deepcopy(packet), auth)
        losses = report["losses"]
    validate(internal, "patient_packet")
    validate_packet_facts(internal)
    cov = internal["coverage"]
    return {"schema_version": packet.get("schema_version"), "valid": True,
            "n_facts": len(internal["facts"]), "adapter_losses": losses,
            "assessed_fact_keys": cov["assessed_fact_keys"], "unassessed_fact_keys": cov["unassessed_fact_keys"],
            "authorized_completeness_records": len(cov["completeness"]),
            "anchor": internal["evaluation_context"]["anchor"], "mode": internal["evaluation_context"]["mode"],
            "warnings": internal.get("warnings", [])}


def evaluate_pack(pack: dict, packet: dict, context: Optional[dict] = None) -> Dict[str, Any]:
    generated_at = packet.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise StructuralError("packet.generated_at is required (the matcher never reads a clock)")
    rid = derive_result_id(pack, packet, context, generated_at)
    return pipeline.evaluate(copy.deepcopy(pack), copy.deepcopy(packet), copy.deepcopy(context),
                             result_id=rid, generated_at=generated_at)


def _brief(cr: dict) -> Dict[str, Any]:
    return {"criterion_id": cr["criterion_id"], "type": cr["criterion_type"], "outcome": cr["outcome"],
            "reason_code": cr.get("reason_code"), "source_text": cr["criterion_source_text"],
            "fact_ids": [r["fact_id"] for r in cr.get("fact_references") or []]}


def summarize(trial: Optional[dict], trial_id: str, pack: dict, pack_source: str, result: dict,
              prob: Dict[str, Any], *, max_items: int = 6) -> Dict[str, Any]:
    crs = result["criterion_results"]
    hard = [c for c in crs if c["hardness"] == "hard"]
    blocking = [_brief(c) for c in hard if c["outcome"] == "resolved_disqualifier"]
    met = [_brief(c) for c in hard if c["outcome"] in ("satisfied", "clear")]
    open_ = [_brief(c) for c in hard if c["outcome"] == "unresolved"]
    procedural = [c["criterion_source_text"] for c in crs if c["hardness"] == "procedural_pre_screen"]
    state = result["trial_eligibility_state"]
    t = trial or {}
    return {
        "trial_id": trial_id, "title": t.get("short_title") or t.get("title"), "registry": t.get("registry"),
        "status": t.get("status_detail"), "phase": t.get("phase"), "location": t.get("geo_label"),
        "best_site": t.get("best_site"), "url": t.get("url"),
        "eligibility_state": state, "eligibility_meaning": STATE_MEANING[state],
        "probability": prob["probability"], "probability_confidence": prob["confidence"],
        "pack_source": pack_source, "pack_id": pack["pack_id"],
        "criteria_counts": {"hard": len(hard), "met": len(met), "unresolved": len(open_),
                            "disqualifying": len(blocking), "procedural": len(procedural)},
        "excluded_by": blocking,
        "met": met[:max_items],
        "to_check": [f for f in prob["factors"] if f["criterion_id"]][:max_items],
        "notes": [n for n in result.get("notes", []) if not n.startswith("adapter loss")][:5],
    }


class Screener:
    def __init__(self, catalog: TrialCatalog, store: PackStore):
        self.catalog = catalog
        self.store = store

    def match(self, packet: dict, trial_id: str, context: Optional[dict] = None,
              *, include_full_result: bool = False) -> Dict[str, Any]:
        trial = self.catalog.get(trial_id)
        pack, source = resolve_pack(trial, trial_id, self.store)
        if pack is None:
            raise KeyError(f"unknown trial {trial_id!r}: not in the catalog and no curated pack")
        result = evaluate_pack(pack, packet, context)
        prob = estimate(result, pack, patient_profile(packet), trial, source)
        out = summarize(trial, trial_id, pack, source, result, prob, max_items=50)
        out["probability_detail"] = prob
        out["disclaimer"] = DISCLAIMER
        if include_full_result:
            out["trial_result"] = result
        return out

    def screen(self, packet: dict, query: Optional[str] = None, *, context: Optional[dict] = None,
               trial_ids: Optional[List[str]] = None, recruiting_only: bool = False,
               max_geo_rank: Optional[int] = None, registry: Optional[str] = None, phase: Optional[str] = None,
               limit: int = 30, min_probability: float = 0.0) -> Dict[str, Any]:
        check_packet(packet, context)  # packet defects abort; later StructuralErrors are pack defects
        profile = patient_profile(packet)
        if trial_ids:
            candidates = [{"trial_id": t} for t in trial_ids]
            search_info = {"trial_ids": trial_ids}
        else:
            q = query or " ".join(profile["diagnosis_terms"])
            if not q.strip():
                raise ValueError("no search query given and the packet has no mappable ICD-10 diagnosis; "
                                 "pass `query` (e.g. 'colorectal KRAS')")
            # Diagnosis-derived terms are alternatives (colorectal / colon / rectal), so match any of them.
            found = self.catalog.search(q, available_only=True, recruiting_only=recruiting_only,
                                        max_geo_rank=max_geo_rank, registry=registry, phase=phase,
                                        sort="relevance", limit=limit, mode="auto" if query else "or")
            candidates = found["results"]
            search_info = {**found["query_used"], "derived_from_diagnosis": query is None,
                           "total_matches": found["total"]}

        excluded, can_apply, errors = [], [], []
        for c in candidates:
            tid = c["trial_id"]
            try:
                trial = self.catalog.get(tid)
                pack, source = resolve_pack(trial, tid, self.store)
                if pack is None:
                    errors.append({"trial_id": tid, "error": "unknown trial"})
                    continue
                result = evaluate_pack(pack, packet, context)
            except StructuralError as e:
                errors.append({"trial_id": tid, "error": f"{type(e).__name__}: {e}"})
                continue
            prob = estimate(result, pack, profile, trial, source)
            s = summarize(trial, tid, pack, source, result, prob)
            if result["trial_eligibility_state"] == "ineligible":
                excluded.append(s)
            elif s["probability"] >= min_probability:
                can_apply.append(s)

        can_apply.sort(key=lambda s: (-s["probability"], STATE_ORDER[s["eligibility_state"]],
                                      s.get("location") or "", s["trial_id"]))
        excluded.sort(key=lambda s: s["trial_id"])
        return {
            "patient_ref": packet.get("patient_ref"),
            "search": search_info,
            "patient_profile_used": {"age": profile["age"], "age_band": profile["age_band"],
                                     "gender": profile["gender"], "icd10": profile["icd10"],
                                     "diagnosis_terms": profile["diagnosis_terms"]},
            "counts": {"evaluated": len(excluded) + len(can_apply), "excluded": len(excluded),
                       "can_apply": len(can_apply), "errors": len(errors)},
            "can_apply": can_apply,
            "excluded": excluded,
            "errors": errors,
            "disclaimer": DISCLAIMER,
        }
