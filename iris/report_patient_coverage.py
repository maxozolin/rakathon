"""Render restricted aggregate audit results; never includes patient examples."""
import json
from pathlib import Path
from audit_patient_coverage import ROOT, OUTPUT


def main():
    data = json.loads((OUTPUT / 'coverage.json').read_text())
    total = data['patient_bundles_scanned']
    def n(value):
        return f'{value:,} ({value / total:.1%})'
    lines = [
        '# Restricted local patient matching coverage audit', '',
        '## Handling and scope', '',
        '**Restricted: approved event patient-data processors only.** Do not provide this report, '
        'detailed counts, source files or evidence pointers to models without approved access.', '',
        'Audit performed locally on 17 October 2026. No external model/service calls or IRIS patient '
        'readback. Counts describe source presence and regex candidates, not clinical fact accuracy. '
        'No deliberate demographic/diagnosis generalization was reversed.', '',
        f'Patient transaction bundles scanned: **{total:,}**. This audits the local package, '
        'not completion or persistence of the IRIS upload.', '',
        '## Structured source coverage', '',
        '| Source field / candidate conjunction | Patients |', '|---|---:|',
    ]
    for key, value in sorted(data['structured_patient_presence'].items()):
        lines.append(f'| `{key}` | {n(value)} |')
    lines += ['', 'Presence of a Condition does not confirm primary tumor/histology; medication '
              'events do not establish an administered regimen or therapy line. Panel conjunctions '
              'are any-time co-presence, not temporally aligned or unit-validated panels.', '',
              '## Narrative candidate coverage', '',
              '| Feature | Any mention | Result/context candidate | Ambiguous nearby context |',
              '|---|---:|---:|---:|']
    for feature, values in data['narrative_patient_coverage'].items():
        lines.append(f"| `{feature}` | {n(values.get('mention', 0))} | "
                     f"{n(values.get('candidate', 0))} | {n(values.get('ambiguous_context', 0))} |")
    lines += ['', 'All columns count distinct patients. Ambiguous context can overlap other columns '
              'and does not certify that remaining candidates are unambiguous. Metastatic/recurrence '
              'candidate rules deliberately count mentions including negation/history; they are NOT '
              'positive disease assertions. Biomarker candidates can include explicit negatives, '
              'family history or boilerplate. Marker/scale mentions without values are not results.', '',
              '## Laboratory label coverage', '',
              '| Analyte label candidate | Any matching label | Numeric value + unit + date present | NČLP supplied |',
              '|---|---:|---:|---:|']
    for feature, values in data['lab_patient_label_coverage'].items():
        lines.append(f"| `{feature}` | {n(values.get('any_test_label', 0))} | "
                     f"{n(values.get('numeric_unit_date_present_not_validated', 0))} | "
                     f"{n(values.get('nclp_present', 0))} |")
    lines += ['', 'Lab labels are regex candidates, not validated analyte mappings. A low/zero label '
              'match does not prove the analyte is absent: local abbreviations/method codes may be '
              'missed. Numeric/unit/date presence is not unit normalization, correct assay, current '
              'screening eligibility or contemporaneous panel coverage. hCG is not automatically a '
              'pregnancy-screening result. ANC must not be inferred from neutrophil percentage.', '',
              '## Interpretation and extraction priorities', '',
              '1. Implement explicit ECOG/Karnofsky extraction and preserve ranges/scale/time; assess '
              'a reviewed sample for copied history and attribution before using results.',
              '2. Extract explicit TNM/stage and histology with disease/specimen context; primary '
              'disease and metastatic/recurrence polarity need adjudication, not keywords.',
              '3. Validate biomarker extraction with assay/result/specimen context and family-history/'
              'panel-boilerplate checks. Do not infer not-tested from absence.',
              '4. Build reviewed local analyte/unit and agent-class mappings; then measure validated '
              'coverage, not this candidate coverage.',
              '5. Reconstruct therapy lines only from explicit evidence; use actual administration/'
              'narrative context, not billing counts.',
              '6. RECIST, tissue availability, present safety status and willingness require explicit '
              'evidence or current manual confirmation. Missing hard requirements remain unresolved.', '',
              'These results show where extraction development can start, not that the minimum '
              'patient packet has already been produced. No clinical sensitivity, specificity, '
              'precision or completeness is established.', '',
              '## Method and limitations', '',
              'Implementation: `iris/audit_patient_coverage.py`; exact regex patterns/version: '
              '`.opencode-secrets/patient-coverage/rules.json`; aggregate JSON: '
              '`.opencode-secrets/patient-coverage/coverage.json`; local candidate evidence pointers: '
              '`.opencode-secrets/patient-coverage/candidate-pointers.ndjson`.', '',
              'Evidence pointers include patient/resource identifiers and normalized-text offsets '
              'but no excerpts. Keep them protected. Matching text is Unicode accent-normalized; '
              'plain-text attachments take priority over HTML; imaging conclusions are included. '
              'Exact normalized text duplicates are skipped per patient, not across patients. '
              'Near-duplicate copy-forward remains possible.', '',
              'Synthetic regression tests passed for scale/range syntax, molecular EGFR vs renal '
              'eGFR, TNM vs institutional abbreviations, therapy vs fracture lines, marker boilerplate '
              'and absolute-neutrophil label distinctions. Tests are not clinical accuracy validation.', '',
              'Quality counters (restricted):', '']
    for key, value in data['quality'].items():
        lines.append(f'- `{key}`: {value:,}')
    lines += ['', 'Not performed: patient-subject adjudication, negation/history/conflict resolution, '
              'molecular assay normalization, clinician review, freshness evaluation, site mapping, '
              'or recovery of suppressed facts. Shifted dates do not justify comparisons with real '
              'today. Do not treat possible source availability as confirmation of current eligibility.', '']
    report = ROOT / 'reports/EU_RESTRICTED_PATIENT_COVERAGE.md'
    report.write_text('\n'.join(lines))
    report.chmod(0o600)
    print('Restricted coverage report rendered; no patient-level content emitted.')


if __name__ == '__main__':
    main()
