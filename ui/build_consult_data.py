"""Regenerate the synthetic data block embedded in ui/consult.html.

Runs the real matcher over the synthetic demo packs and patients
(matcher/tools/mock_patient_demo.py) and writes the results, plus display
strings for each synthetic fact, into the <script id="consult-data"> block.
Synthetic data only. Public trial metadata is read from the local ClinicalTrials.gov
snapshot when it is present.

    python ui/build_consult_data.py
"""

import copy
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "matcher"))
sys.path.insert(0, str(ROOT / "matcher" / "tools"))

from avicenna_matcher import pipeline  # noqa: E402
from avicenna_matcher.explain import category  # noqa: E402
import mock_patient_demo as demo  # noqa: E402

HTML = ROOT / "ui" / "consult.html"
CTGOV = ROOT / "data" / "ctgov" / "ctgov.sqlite"

SHORT = {
    "NCT06252649": ("CodeBreaK 301", "Sotorasib + panitumumab + FOLFIRI vs FOLFIRI ± bevacizumab", "KRAS G12C mCRC, first line"),
    "NCT07218380": ("FORAGER-2", "Vepugratinib + enfortumab vedotin + pembrolizumab vs placebo combination", "FGFR3-altered mUC, untreated"),
    "NCT07062965": ("PF-07248144 + fulvestrant", "PF-07248144 + fulvestrant vs investigator’s choice", "HR+/HER2− mBC after CDK4/6i"),
}

PATIENT_LABEL = {
    "fict-p1": ("P1", "Metastatic breast cancer, HR+/HER2−, after CDK4/6 inhibitor"),
    "fict-p2": ("P2", "Metastatic colorectal cancer, KRAS G12C, treatment-naïve"),
    "fict-p3": ("P3", "Metastatic urothelial carcinoma, FGFR3+, ECOG 2"),
    "fict-p4": ("P4", "Metastatic rectal cancer, KRAS G12C, prior sotorasib"),
    "fict-p5": ("P5", "Colorectal cancer, sparse record"),
}

CODES = {
    "C18.7": "Malignant neoplasm of sigmoid colon", "C18.2": "Malignant neoplasm of ascending colon",
    "C20": "Malignant neoplasm of rectum", "C50.4": "Malignant neoplasm of upper-outer quadrant of breast",
    "C67.9": "Malignant neoplasm of bladder, unspecified",
    "8140/3": "Adenocarcinoma, NOS", "8120/3": "Transitional cell carcinoma, NOS",
}

KEY_LABEL = {
    "demographics.age": "Age", "demographics.administrative_gender": "Sex", "disease.primary": "Primary diagnosis",
    "disease.histology": "Histology", "disease.stage": "Stage", "disease.metastatic": "Metastatic disease",
    "disease.recist_measurable": "RECIST-measurable disease", "disease.cns_metastases": "CNS metastases",
    "disease.condition": "Condition", "performance.status": "Performance status", "therapy.event": "Therapy history",
    "biomarker.result": "Biomarker", "lab.result": "Laboratory results", "logistics.treating_center": "Treating centre",
}

# Clinician-facing wording; the engine code stays visible beside it for traceability.
REASON_COPY = {
    "opaque_text": ("Read trial wording", "This criterion was not broken into checkable parts. Read the trial wording and check the chart."),
    "fact_missing": ("Not in record", "The packet has no data for this. Check the chart or order the test."),
    "partial_atomization": ("Partly checkable", "Only part of this criterion could be checked, so a failure cannot be concluded from that part alone."),
    "absence_not_established": ("Absence not confirmed", "Nothing in the packet confirms this is absent. Missing data is not treated as “no”."),
    "unit_mismatch": ("Different scale", "The record uses a scale the criterion does not accept (for example, Karnofsky against an ECOG limit). Scales are not converted."),
    "exposure_membership_unknown": ("Drug class unclear", "A prior therapy is recorded, but whether it belongs to the excluded class is not established."),
}

OUTCOME_WHY = {
    ("satisfied", "inclusion"): "Recorded evidence meets this requirement.",
    ("clear", "exclusion"): "Recorded evidence rules this exclusion out.",
    ("resolved_disqualifier", "inclusion"): "Recorded evidence contradicts this requirement.",
    ("resolved_disqualifier", "exclusion"): "Recorded evidence meets this exclusion.",
    ("non_blocking", "exclusion"): "Investigator judgement at screening; does not block pre-screening.",
    ("non_blocking", "inclusion"): "Investigator judgement at screening; does not block pre-screening.",
}


def fmt_fact(f):
    v, key = f["value"], f["fact_key"]
    neg = f["assertion"] == "explicit_negative"
    k = v.get("kind")
    if k == "integer":
        text = f"{v['value']} {v['unit']}"
    elif k == "coded" and key == "disease.condition":
        text = ("No " if neg else "") + v["code"].replace("_", " ")
    elif k == "coded":
        text = f"{v['code']} · {CODES.get(v['code'], v.get('display', ''))}"
    elif k == "boolean":
        text = "Yes" if v["value"] else "No"
    elif k == "scored_instrument":
        name = "ECOG" if v["instrument"]["code"] == "89247-1" else "Karnofsky"
        text = f"{name} {v['value']}"
    elif k == "biomarker":
        text = f"{v['marker']['code'].replace('_', ' p.')} {v['result']['code'].replace('_', ' ')}"
    elif k == "therapy_event":
        text = " + ".join(a["code"] for a in v["agents"]) + f" ({v['intent']} setting)"
    elif k == "scoped_absence":
        c = f["scope"]["concepts"]
        what = ", ".join(c["agents"] or c["classes"]).replace("_", " ")
        setting = f["scope"]["disease_setting"].replace("_", " ")
        text = f"Never received: {what} ({setting})"
    else:
        text = json.dumps(v)
    t = (f.get("effective_time") or {}).get("value")
    ev = f["evidence"][0]
    return {
        "id": f["fact_id"], "key": key, "label": KEY_LABEL.get(key, key), "text": text,
        "date": t, "reviewed": f["review_status"] == "reviewed",
        "negative": neg, "source": ev["source_kind"].replace("_", " "),
    }


def _norm(t):
    return re.sub(r"\s+", " ", t.replace("\u2264", "<=").replace("\u2265", ">=")).strip().lower()


def registry_lines(text):
    """Split public eligibility text into (section, bullet) pairs."""
    out, sec = [], None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("inclusion criteria"):
            sec = "inclusion"; continue
        if low.startswith("exclusion criteria"):
            sec = "exclusion"; continue
        out.append((sec, re.sub(r"^[*\-\u2022]\s*", "", line)))
    return out


def parent_text(fragment, ctype, lines):
    """Full registry bullet that an atomized fragment came from; None when it is already whole."""
    pieces = [_norm(x).strip(" .,;") for x in fragment.split("\u2026")]
    pieces = [x for x in pieces if x]
    cands = [l for sec, l in lines if sec in (ctype, None)]
    exact = [l for l in cands if all(x in _norm(l) for x in pieces)]
    if not exact:
        words = set(re.findall(r"[a-z0-9]+", " ".join(pieces)))
        scored = sorted(((len(words & set(re.findall(r"[a-z0-9]+", _norm(l)))) / max(len(words), 1), l) for l in cands),
                        reverse=True)
        exact = [scored[0][1]] if scored and scored[0][0] >= 0.75 else []
    if not exact:
        return None
    full = exact[0]
    return None if _norm(full).strip(" .") == _norm(fragment).strip(" .") else full


def trial_meta():
    meta = {}
    con = sqlite3.connect(f"file:{CTGOV}?mode=ro", uri=True) if CTGOV.exists() else None
    for nct in demo.PACKS:
        short, regimen, population = SHORT[nct]
        m = {"id": nct, "short": short, "regimen": regimen, "population": population,
             "title": "", "phase": "", "status": "", "sites_cz": [], "snapshot": "", "lines": []}
        if con:
            r = con.execute("select brief_title, phase_json, overall_status, locations_json, ingested_at, eligibility_text "
                            "from ctgov_studies where nct_id=?", (nct,)).fetchone()
            if r:
                m["title"] = r[0]
                m["phase"] = ", ".join(p.replace("PHASE", "Phase ") for p in json.loads(r[1] or "[]"))
                m["status"] = r[2]
                m["sites_cz"] = [{"facility": l["facility"], "city": l["city"], "status": l.get("status")}
                                 for l in json.loads(r[3] or "[]") if l.get("country") == "Czechia"]
                m["snapshot"] = (r[4] or "")[:10]
                m["lines"] = registry_lines(r[5])
        meta[nct] = m
    return meta


def build():
    patients, results = {}, []
    trials = trial_meta()
    for pt in demo.PATIENTS.values():
        ref = pt["patient_ref"]
        code, summary = PATIENT_LABEL[ref]
        patients[ref] = {
            "ref": ref, "code": code, "summary": summary,
            "anchor": pt["evaluation_context"]["anchor"]["value"],
            "mode": pt["evaluation_context"]["mode"],
            "facts": {f["fact_id"]: fmt_fact(f) for f in pt["facts"]},
            "unassessed": [KEY_LABEL.get(k, k) for k in pt["coverage"]["unassessed_fact_keys"]],
        }
        for nct, pk in demo.PACKS.items():
            r = pipeline.evaluate(copy.deepcopy(pk), copy.deepcopy(pt), demo.SITE_POLICY,
                                  result_id=f"demo-{nct}-{pt['packet_id']}", generated_at=demo.GEN)
            crit = []
            for c in r["criterion_results"]:
                rc = c["reason_code"]
                crit.append({
                    "id": c["criterion_id"], "type": c["criterion_type"], "text": c["criterion_source_text"],
                    "parent": parent_text(c["criterion_source_text"], c["criterion_type"], trials[nct]["lines"]),
                    "outcome": c["outcome"], "hardness": c["hardness"], "reason": rc,
                    "reason_category": category(rc) if rc else None,
                    "reason_title": REASON_COPY.get(rc, (rc, ""))[0] if rc else None,
                    "why": REASON_COPY[rc][1] if rc in REASON_COPY else OUTCOME_WHY.get((c["outcome"], c["criterion_type"]), ""),
                    "facts": [fr["fact_id"] for fr in c["fact_references"]],
                    "atoms": [{"id": a["atom_id"], "text": a.get("source_text") or "", "outcome": a["outcome"],
                               "reason": a["reason_code"]} for a in c.get("atom_results", [])],
                })
            arm = r["per_arm_results"][0]
            results.append({
                "trial": nct, "patient": ref, "state": r["trial_eligibility_state"],
                "policy": r["policy_version"], "generated": r["generated_at"],
                "arm": {"id": arm["arm_id"], "state": arm["arm_eligibility_state"],
                        "blocking": arm["blocking_criteria"], "manual": arm["manual_review_criteria"],
                        "applicable": arm["evidence_coverage"]["applicable_count"],
                        "unassessed": arm["evidence_coverage"]["unassessed_criteria"]},
                "criteria": crit, "notes": r.get("notes", []),
            })
    for t in trials.values():
        del t["lines"]
    return {"site_policy": demo.SITE_POLICY, "trials": trials, "patients": patients, "results": results}


def main():
    data = json.dumps(build(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = HTML.read_text()
    new, n = re.subn(r'(<script id="consult-data" type="application/json">)(.*?)(</script>)',
                     lambda m: m.group(1) + data + m.group(3), html, flags=re.S)
    if n != 1:
        sys.exit("consult-data block not found in ui/consult.html")
    HTML.write_text(new)
    print(f"wrote {len(data)} bytes of synthetic data into {HTML.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
