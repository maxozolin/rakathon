"""Run fictional canonical patients against hand-atomized public CT.gov trials.

DEMO ONLY. No real patient data: every patient below is invented. The three trial packs are
hand-atomized by a developer from public ClinicalTrials.gov eligibility text (there is no
atomizer yet), abbreviated/paraphrased, so each pack declares criteria_completeness=partial.
Vague or judgment criteria are kept opaque_text; nothing is invented to make them evaluable.

    python matcher/tools/mock_patient_demo.py [--ctgov data/ctgov/ctgov.sqlite] [--json OUT]
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avicenna_matcher import pipeline  # noqa: E402

GEN = "2026-04-01T12:00:00Z"
SNAP = "synthetic-demo-v1"
ANCHOR = "2026-04-01"

# ---------------------------------------------------------------------------
# Pack helpers
# ---------------------------------------------------------------------------


def atom(aid, ptype, src, **kw):
    return {"atom_id": aid, "predicate_type": ptype, "arm_scope": None, "source_text": src, **kw}


def cmp(aid, src, key, comparator, threshold, **kw):
    return atom(aid, "simple_comparison", src, fact_key=key, comparator=comparator, threshold=threshold, **kw)


def crit(cid, ctype, src, atoms, note="complete", logic=None, hardness="hard"):
    c = {"criterion_id": cid, "criterion_type": ctype, "hardness": hardness, "arm_scope": None,
         "source_text": src, "atoms": atoms, "completeness_note": note}
    if logic:
        c["logic"] = {"op": logic}
    return c


def opaque(cid, ctype, src, hardness="hard"):
    return crit(cid, ctype, src, [], note="opaque_text", hardness=hardness)


def pack(trial_id, criteria):
    return {"schema_version": "avicenna.criteria-pack/0.1", "pack_id": f"demo-hand-{trial_id}",
            "trial_id": trial_id, "criteria_completeness": "partial", "generated_at": "2026-04-01T00:00:00Z",
            "arms": [{"arm_id": "main", "arm_name": "All arms (demo)", "study_type": "interventional"}],
            "criteria": criteria}


# Shared terminology binding (prompts/*_BUILDER_PROMPT.md): codes must match exactly on both sides.
MARK = "avicenna-marker/1"
RES = "avicenna-result/1"
ECOG_LE = lambda n: {"value": n, "unit": "{ECOG}"}
AGE18 = cmp("a", "Age ≥ 18 years", "demographics.age", "ge", {"value": 18, "unit": "a"})


def marker(aid, src, code, result):
    return cmp(aid, src, "biomarker.result", "eq", {"system": RES, "code": result},
               concept={"system": MARK, "code": code})


def prior(aid, src, concepts, setting=None):
    scope = {"time_extent": "lifetime", "concepts": concepts, "ontology_version_pin": "avicenna-seed/1.0.0"}
    if setting:
        scope["setting"] = setting
    return atom(aid, "not_exists", src, fact_key="therapy.event", scope=scope)


def icd(*codes):
    return [{"system": "ICD-10", "code": c} for c in codes]


def mets_or_la(src):
    return [cmp("m", src, "disease.metastatic", "eq", True),
            cmp("l", src, "disease.locally_advanced", "eq", True)]


# Encoding rules (TRIAL_DATA_STANDARD.md §6, MATCHER_DESIGN.md §6/§8):
# * Investigator judgment / consent / willingness → procedural_pre_screen (visible, non-blocking).
# * `partial` lets a criterion resolve only in the NON-disqualifying direction, so it is used
#   only where the encoded part is SUFFICIENT for an inclusion or NECESSARY for an exclusion.
#   Otherwise the source sentence is split: an AND-ed inclusion / OR-ed exclusion becomes
#   separate criteria (each sound on its own); the unencodable remainder stays opaque_text.
# * Protocol-defined thresholds absent from the public text ("adequate organ function") and
#   concepts outside the vocabulary (CTCAE grades, line counts, screening-visit findings)
#   stay opaque_text. Nothing is defaulted.
SYSTEMIC = ["chemotherapy", "immunotherapy", "endocrine", "targeted", "adc", "parp_inhibitor"]
COND = "avicenna-condition/1"        # local condition codes (standard allows local codes)


def condition(aid, src, code, relation):
    return cmp(aid, src, "disease.condition", "eq", {"system": COND, "code": code}, relation=relation)


AGE_SRC = "Minimum age: 18 Years (registry structured field)"

PACKS = {
    "NCT07062965": pack("NCT07062965", [
        crit("inc:age", "inclusion", AGE_SRC, [AGE18]),
        # Inclusion 1 = breast ∧ HR+ ∧ HER2− ∧ (LA ∨ metastatic) ∧ not curable → split.
        crit("inc:breast", "inclusion", "Confirmed diagnosis of … breast cancer",
             [cmp("d", "breast cancer", "disease.primary", "in_set", icd(*[f"C50.{i}" for i in range(10)]))]),
        crit("inc:hr", "inclusion", "HR-positive",
             [marker("er", "ER+", "ER", "positive"), marker("pr", "PR+", "PR", "positive")], logic="any"),
        crit("inc:her2", "inclusion", "HER2-negative", [marker("h", "HER2−", "HER2", "negative")]),
        crit("inc:adv", "inclusion", "with evidence of locally advanced or metastatic disease",
             mets_or_la("locally advanced or metastatic"), logic="any"),
        opaque("inc:noncur", "inclusion", "which is not amenable to surgical resection or radiation therapy "
                                          "with curative intent"),
        opaque("inc:cdk", "inclusion", "Prior CDK4/6 inhibitor therapy in combination with endocrine therapy in "
               "advance metastatic setting or in adjuvant setting with documented progression during or within "
               "12 months after the last dose of CDK4/6i."),
        # (Inclusion 3 is a permissive clarification, not a requirement — not encoded.)
        crit("inc:meas", "inclusion", "Measurable disease evaluable per RECIST v.1.1 or non-measurable "
             "bone-only disease", [cmp("r", "RECIST-measurable", "disease.recist_measurable", "eq", True)],
             note="partial"),                       # measurable is SUFFICIENT; bone-only branch not encoded
        crit("inc:ecog", "inclusion", "ECOG Performance Status 0 or 1",
             [cmp("e", "ECOG ≤ 1", "performance.status", "le", ECOG_LE(1))]),
        crit("exc:pik3", "exclusion", "Documented detectable PIK3CA/AKT1/PTEN alterations in tissue",
             [marker("p", "PIK3CA", "PIK3CA", "detected"), marker("k", "AKT1", "AKT1", "detected"),
              marker("t", "PTEN", "PTEN", "detected")], logic="any", note="partial"),  # specimen=tissue unchecked
        opaque("exc:lines", "exclusion", "Received greater than two prior lines of systemic therapy in the "
                                         "advance or metastatic setting"),           # line counting unsupported
        crit("exc:chemo", "exclusion", "Had received any prior chemotherapy, including antibody drug conjugates "
             "(ADCs), in advance or metastatic setting. … (neo)adjuvant … not excluded.",
             [prior("n", "prior chemo/ADC, advanced", ["chemotherapy", "adc"], "advanced")], logic="not"),
        opaque("exc:med", "exclusion", "Any medical or psychiatric condition that may increase the risk of study "
               "participation or make the participant inappropriate for the study.",
               hardness="procedural_pre_screen"),
        opaque("exc:organ", "exclusion", "Renal impairment, hepatic dysfunction, or hematologic abnormalities."),
    ]),
    "NCT06252649": pack("NCT06252649", [
        crit("inc:age", "inclusion", AGE_SRC, [AGE18]),
        # Inclusion 1 = metastatic ∧ colorectal ∧ adenocarcinoma ∧ KRAS G12C (local validated assay) → split.
        crit("inc:crc", "inclusion", "Pathologically documented … colorectal …",
             [cmp("d", "CRC", "disease.primary", "in_set", icd(*[f"C18.{i}" for i in range(10)], "C19", "C20"))]),
        crit("inc:adeno", "inclusion", "… adenocarcinoma …",
             [cmp("h", "adenocarcinoma", "disease.histology", "eq", {"system": "ICD-O-3", "code": "8140/3"})]),
        crit("inc:met", "inclusion", "… metastatic …", [cmp("m", "metastatic", "disease.metastatic", "eq", True)]),
        crit("inc:g12c", "inclusion", "… with KRAS p.G12C mutation …",
             [marker("k", "KRAS G12C", "KRAS_G12C", "detected")]),
        opaque("inc:g12c-assay", "inclusion", "… by a locally validated assay."),   # assay validation: not in packet
        opaque("inc:central", "inclusion", "Central laboratory detection of KRAS p.G12C mutation."),
        crit("inc:meas", "inclusion", "Measurable metastatic disease per RECIST v1.1 criteria.",
             [cmp("r", "RECIST-measurable", "disease.recist_measurable", "eq", True)]),
        crit("inc:ecog", "inclusion", "ECOG Performance Status of ≤ 1.",
             [cmp("e", "ECOG ≤ 1", "performance.status", "le", ECOG_LE(1))]),
        opaque("inc:organ", "inclusion", "Adequate organ function."),
        crit("exc:brain", "exclusion", "Active, untreated brain metastases.",
             [cmp("c", "brain metastases", "disease.cns_metastases", "eq", True)],
             note="partial"),                       # brain mets NECESSARY; active/untreated not encoded
        crit("exc:lepto", "exclusion", "Leptomeningeal disease",
             [condition("l", "leptomeningeal disease", "leptomeningeal_disease", "current")]),
        crit("exc:g12ci", "exclusion", "Previous treatment with a KRAS p.G12C inhibitor",
             [prior("n", "prior sotorasib/adagrasib", ["sotorasib", "adagrasib"])], logic="not"),
        # OR-ed exclusion → split: history (encodable) vs baseline-CT finding (screening visit).
        crit("exc:ild-hx", "exclusion", "History of interstitial pneumonitis or pulmonary fibrosis",
             [condition("i", "interstitial pneumonitis", "interstitial_pneumonitis", "ever"),
              condition("f", "pulmonary fibrosis", "pulmonary_fibrosis", "ever")], logic="any"),
        opaque("exc:ild-ct", "exclusion", "or evidence of interstitial pneumonitis or pulmonary fibrosis on "
                                          "baseline CT scan"),
    ]),
    "NCT07218380": pack("NCT07218380", [
        crit("inc:age", "inclusion", AGE_SRC, [AGE18]),
        # Inclusion 1 = urothelial (mixed allowed) ∧ histologically confirmed ∧ unresectable LA ∨ metastatic.
        crit("inc:uro-site", "inclusion", "… urothelial cancer (urothelium lines the urinary tract: renal pelvis, "
             "ureter, bladder, urethra)", [cmp("s", "urinary-tract primary", "disease.primary", "in_set",
                                              icd("C65", "C66", *[f"C67.{i}" for i in range(10)], "C68.0", "C68.8",
                                                  "C68.9"))]),       # NECESSARY sub-condition of inclusion 1
        crit("inc:uro", "inclusion", "Have histologically confirmed … urothelial cancer. Individuals with mixed "
             "histology other than small cell or neuroendocrine carcinoma are eligible if a urothelial component "
             "is present.", [cmp("h", "urothelial carcinoma", "disease.histology", "eq",
                                 {"system": "ICD-O-3", "code": "8120/3"})],
             note="partial"),                       # pure urothelial SUFFICIENT; mixed-histology branch not encoded
        crit("inc:adv", "inclusion", "unresectable locally advanced or metastatic",
             [cmp("m", "metastatic", "disease.metastatic", "eq", True)],
             note="partial"),                       # metastatic SUFFICIENT; unresectable-LA branch not encoded
        # Inclusion 2 = FGFR3 alteration ∧ "qualifying" (protocol list) ∧ sample timing → split.
        crit("inc:fgfr3", "inclusion", "Have a … FGFR3 genetic alteration determined via molecular testing",
             [marker("f", "FGFR3", "FGFR3", "detected")]),
        opaque("inc:fgfr3-q", "inclusion", "qualifying … from a tumor or blood sample obtained at or any time "
                                           "after diagnosis of advanced or metastatic urothelial cancer."),
        crit("inc:meas", "inclusion", "Have measurable disease by investigator assessment defined by RECIST v1.1",
             [cmp("r", "RECIST-measurable", "disease.recist_measurable", "eq", True)]),
        crit("inc:ecog", "inclusion", "Have an ECOG performance status of 0 to 2.",
             [cmp("e", "ECOG ≤ 2", "performance.status", "le", ECOG_LE(2))]),
        opaque("inc:labs", "inclusion", "Have adequate laboratory parameters"),
        crit("exc:prior", "exclusion", "Have received prior systemic therapy for locally advanced or metastatic "
             "urothelial cancer (mUC).", [prior("n", "prior systemic therapy, advanced", SYSTEMIC, "advanced")],
             logic="not"),
        opaque("exc:tox", "exclusion", "Have any unresolved toxicities greater than Grade 1 CTCAE v5.0 from prior "
                                       "neoadjuvant or adjuvant systemic therapy."),
        opaque("exc:neuro", "exclusion", "Have ongoing sensory or motor neuropathy of Grade 2 or higher"),
        # OR-ed exclusion → split.
        crit("exc:cns", "exclusion", "Have untreated or uncontrolled central nervous system (CNS) involvement",
             [cmp("c", "CNS metastases", "disease.cns_metastases", "eq", True)],
             note="partial"),                       # CNS mets NECESSARY; untreated/uncontrolled not encoded
        crit("exc:lepto", "exclusion", "or any history of leptomeningeal disease.",
             [condition("l", "leptomeningeal disease", "leptomeningeal_disease", "ever")]),
        opaque("exc:eye", "exclusion", "Current evidence corneal keratopathy or retinal disorder confirmed by "
                                       "ocular examination at screening."),
    ]),
}

# ---------------------------------------------------------------------------
# Fictional canonical patients (avicenna.patient-packet/1.1.0, shifted_demo)
# ---------------------------------------------------------------------------


def tp(v, precision="day"):
    return {"kind": "point", "value": v, "precision": precision, "time_basis": "shifted_patient_local"}


def F(fid, key, value, *, assertion="positive", t="2026-03-25", review="unreviewed", scope=None, concept=None,
      source_kind="structured", verification="source_assertion"):
    f = {"fact_id": fid, "fact_key": key, "state": "known", "value": value, "missing_reason": None,
         "assertion": assertion, "subject_scope": "patient", "effective_time": tp(t) if t else None,
         "recorded_time": None,
         "evidence": [{"resource_type": "Synthetic", "resource_id": f"syn-{fid}", "version_id": "1",
                       "locator": "value", "source_kind": source_kind, "verification_status": verification}],
         "provenance": {"method": "source_projection", "method_version": "demo/1", "model_id": None,
                        "confidence": None, "input_fact_refs": []},
         "review_status": review, "generalization": {"applied": False, "constraints": []},
         "alternatives": [], "scope": scope}
    if concept:
        f["concept"] = concept
    return f


def age(fid, years):
    return F(fid, "demographics.age", {"kind": "integer", "value": years, "unit": "years"})


def dx(fid, code, key="disease.primary", system="ICD-10"):
    return F(fid, key, {"kind": "coded", "system": system, "code": code, "display": code})


def flag(fid, key, value):
    return F(fid, key, {"kind": "boolean", "value": value}, assertion="positive" if value else "explicit_negative")


def bio(fid, code, result):
    return F(fid, "biomarker.result", {"kind": "biomarker", "marker": {"system": MARK, "code": code},
                                       "result": {"system": RES, "code": result}, "assay": "demo-assay",
                                       "specimen_ref": None, "disease_fact_ref": None}, source_kind="lab")


def no_condition(fid, code):
    return F(fid, "disease.condition", {"kind": "coded", "system": COND, "code": code},
             assertion="explicit_negative", review="reviewed")


def ecog(fid, score):
    return F(fid, "performance.status", {
        "kind": "scored_instrument", "instrument": {"system": "http://loinc.org", "code": "89247-1"},
        "registry_version": "avicenna-instruments/1.0.0", "representation": "numeric",
        "no_interconversion": True, "value": score, "value_high": None, "scale_min": 0, "scale_max": 4, "step": 1})


def karnofsky(fid, score):
    v = ecog(fid, 0)
    v["value"].update(instrument={"system": "http://loinc.org", "code": "89243-0"}, value=score,
                      scale_min=0, scale_max=100, step=10)
    return v


def tx(fid, agents, classes, intent, t="2025-06-01"):
    return F(fid, "therapy.event", {
        "kind": "therapy_event", "agents": [{"system": "inn", "code": a, "display": a} for a in agents],
        "classes": classes, "evidence_kind": "administration", "line": None, "line_context": None,
        "intent": intent, "start": None, "end": None, "progression_time": None, "best_response": None,
        "disease_fact_ref": None}, t=t, source_kind="administration")


def absence(fid, setting, agents=(), classes=()):
    """Reviewed, explicit denial of a scoped exposure (lifetime through the anchor)."""
    scope = {"concepts": {"system": "avicenna-therapy/1", "registry_version": "avicenna-seed/1.0.0",
                          "classes": list(classes), "agents": list(agents)},
             "disease_setting": setting, "disease_fact_ref": None, "disease_scope": "all_diseases",
             "time": {"extent": "lifetime", "time_basis": "shifted_patient_local", "through": tp(ANCHOR)}}
    return F(fid, "therapy.event", {"kind": "scoped_absence", "absent": True}, assertion="explicit_negative",
             review="reviewed", scope=scope, source_kind="manual_review", verification="reviewed")


ALL_SLOTS = ["demographics.age", "demographics.administrative_gender", "disease.primary", "disease.histology",
             "disease.stage", "disease.metastatic", "performance.status", "therapy.event", "biomarker.result",
             "lab.result", "logistics.treating_center"]


def patient(pid, facts):
    assessed = sorted({f["fact_key"] for f in facts})
    return {
        "schema_version": "avicenna.patient-packet/1.1.0", "packet_id": f"demo-{pid}", "patient_ref": f"fict-{pid}",
        "generated_at": GEN, "environment": "synthetic_demo",
        "source_snapshot": {"snapshot_id": SNAP, "ingestion_state": "complete", "extractor_version": "demo/1",
                            "terminology_version": "demo/1"},
        "evaluation_context": {"mode": "shifted_demo", "anchor": tp(ANCHOR),
                               "absolute_screening_recency_allowed": False, "policy_version": "demo-policy-1"},
        "facts": facts,
        "coverage": {"assessed_fact_keys": assessed,
                     "unassessed_fact_keys": [k for k in ALL_SLOTS if k not in assessed],
                     "completeness": []},
        "warnings": [],
    }


PATIENTS = {
    "P1 breast HR+/HER2− post-CDK4/6i": patient("p1", [
        age("ag", 58), dx("dx", "C50.4"), flag("met", "disease.metastatic", True),
        flag("rec", "disease.recist_measurable", True), ecog("ps", 1),
        bio("er", "ER", "positive"), bio("her2", "HER2", "negative"), bio("pik", "PIK3CA", "not_detected"),
        tx("t1", ["palbociclib", "letrozole"], ["targeted", "endocrine"], "advanced"),
        absence("noch", "advanced", classes=["chemotherapy", "adc"]),
    ]),
    "P2 mCRC KRAS G12C, untreated": patient("p2", [
        age("ag", 66), dx("dx", "C18.7"), dx("hist", "8140/3", "disease.histology", "ICD-O-3"),
        flag("met", "disease.metastatic", True), flag("rec", "disease.recist_measurable", True), ecog("ps", 0),
        bio("kras", "KRAS_G12C", "detected"), flag("cns", "disease.cns_metastases", False),
        no_condition("nolm", "leptomeningeal_disease"), no_condition("noip", "interstitial_pneumonitis"),
        no_condition("nopf", "pulmonary_fibrosis"),
        absence("nosys", "advanced", classes=SYSTEMIC),
        absence("nog12", "all_settings", agents=["sotorasib", "adagrasib"]),
    ]),
    "P3 mUC FGFR3+, ECOG 2, prior neoadj. chemo": patient("p3", [
        age("ag", 71), dx("dx", "C67.9"), dx("hist", "8120/3", "disease.histology", "ICD-O-3"),
        flag("met", "disease.metastatic", True), no_condition("nolm", "leptomeningeal_disease"),
        flag("rec", "disease.recist_measurable", True), ecog("ps", 2), bio("fg", "FGFR3", "detected"),
        flag("cns", "disease.cns_metastases", False),
        tx("t1", ["cisplatin", "gemcitabine"], ["chemotherapy"], "neoadjuvant", t="2024-09-01"),
        absence("nosys", "advanced", classes=SYSTEMIC),
    ]),
    "P4 mCRC G12C, prior sotorasib, Karnofsky only": patient("p4", [
        age("ag", 54), dx("dx", "C20"), flag("met", "disease.metastatic", True), karnofsky("ps", 80),
        bio("kras", "KRAS_G12C", "detected"), tx("t1", ["sotorasib"], ["targeted"], "advanced"),
    ]),
    "P5 sparse record (CRC dx only)": patient("p5", [age("ag", 63), dx("dx", "C18.2")]),
}

# ---------------------------------------------------------------------------


def run(ctgov: Path | None, out: Path | None) -> int:
    titles = {}
    if ctgov and ctgov.exists():
        con = sqlite3.connect(f"file:{ctgov}?mode=ro", uri=True)
        for nct in PACKS:
            row = con.execute("select brief_title, overall_status from ctgov_studies where nct_id=?", (nct,)).fetchone()
            titles[nct] = f"{row[0]} [{row[1]}]" if row else "(not in local DB)"
    dump = []
    print(f"site screening_recency_days policy: {SITE_POLICY['screening_recency_days']}")
    for nct, pk in PACKS.items():
        print(f"\n=== {nct}  {titles.get(nct, '')}")
        for pname, pt in PATIENTS.items():
            r = pipeline.evaluate(copy.deepcopy(pk), copy.deepcopy(pt), SITE_POLICY, result_id=f"demo-{nct}-{pt['packet_id']}",
                                  generated_at=GEN)
            dump.append(r)
            arm = r["per_arm_results"][0]
            print(f"\n  {pname:45s} → {r['trial_eligibility_state'].upper()}"
                  f"  (blocking: {', '.join(arm['blocking_criteria']) or '-'})")
            for cr in r["criterion_results"]:
                o = cr["outcome"]
                sym = {"satisfied": "✓", "clear": "✓", "resolved_disqualifier": "✗", "non_blocking": "·"}.get(o, "?")
                print(f"     {sym} {cr['criterion_id']:12s} {o:22s} {cr['reason_code'] or ''}")
    if out:
        out.write_text(json.dumps(dump, indent=2, ensure_ascii=False))
    return 0


# Demo site policy. The public texts state no screening window for ECOG, so a site must
# say how recent a score has to be to stand for "now"; without this the criteria are
# recency_unbounded. A real site sets this under its own reviewed policy.
SITE_POLICY = {"screening_recency_days": {"performance.status": 28, "lab.result": 14}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ctgov", type=Path, default=Path("data/ctgov/ctgov.sqlite"))
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    sys.exit(run(a.ctgov, a.json))
