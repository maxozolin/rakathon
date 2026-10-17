# Avicenna × InterSystems IRIS — brief & plan

> Scope of this note: product brief + what we can/should do with IRIS for Health on Rakathon.  
> Dataset inspection and ingestion guidance are now in `reports/EU_RESTRICTED_IRIS_INGESTION.md` (restricted) and `reports/GENERAL_DATA_GUIDE.md` (privacy-safe).

---

## 1. Brief (from `PRESENTATION.md` + `MISSION.md`)

### Pitch (presentation)

- **Avicenna** helps doctors find the best clinical trial for a patient when stakes are highest.
- It holds a large trial database (Prague → Brno/Ostrava → CZ → Europe → world).
- Doctors should not have to scan that catalog manually.
- **Matching engine runs on InterSystems technology** so matching happens **without reading confidential patient data off hospital servers** → lower cyber risk / insurance burden → simpler go-to-market story.

### Hackathon mission (challenge #1 — AI Trial Matching)

- Convert trial **inclusion/exclusion** criteria into structured form.
- Compare against **pseudonymized, still-protected** patient data. The supplied dataset README explicitly prohibits copying outside the event environment.
- Return a **match score** plus explanation per criterion: met / not met / data missing.
- Client desire: alert that a patient meets criteria **before anyone thinks to look**.
- Deadline: Saturday 13:00 Europe/Prague (Rakathon 2026).
- Location focus: Prague first, then Brno/Ostrava, then CZ, then world.

### How IRIS fits the story

| Layer | Role |
|--------|------|
| **Hospital-side (IRIS)** | Hold patient facts, extract clinical features, evaluate criteria, rank trials, generate explanations, and display patient-specific alerts locally. |
| **Avicenna cloud** | Trial catalog + criteria structuring; sends versioned criteria into hospital. No fetching patient fields, facts, scores, explanations, or charts. |
| **Demo narrative** | “We match in place on InterSystems — PHI doesn’t leave the hospital server.” |

That privacy claim is the InterSystems differentiator in the pitch. Architecture and demo must reinforce it; pseudonymization does not remove the supplied dataset's privacy restrictions.

**Required boundary:** matching stays hospital-side too. Patient-linked scores and explanations are health information, not automatically safe cloud outputs. The clinician UI/alerts stay hospital-side; any future export requires separate approval and privacy controls. The public Azure instance is a synthetic-data mock, not proof of a production hospital security boundary.

---

## 2. What we already have (Rakathon)

| Item | Detail |
|------|--------|
| Product | **InterSystems IRIS for Health Community** on **Azure Container Instances** |
| Resource group | `rg-team16` |
| Container | `aci-irishealth-team16` (Running) |
| Public IP | `20.240.154.131` |
| Ports | **52773** Management Portal + web/FHIR apps; **1972** SuperServer (JDBC/ODBC/Python) |
| User | `_SYSTEM` (password in local `.env` as `IRIS_PASSWORD`) |
| Namespace | `USER` is the original client default; **`AVICENNA`** is the configured Foundation/FHIR mock-hospital namespace. |
| Image | `intersystems/irishealth-community` (digest pinned by portal); observed IRIS for Health **2026.1 Build 235U** |
| FHIR R4 endpoint | `http://20.240.154.131:52773/csp/healthshare/avicenna/fhir/r4` |
| Verified setup | R4 `CapabilityStatement` (`4.0.1`), enabled endpoint, anonymous `Patient` search denied (`401`); no supplied patient data loaded. |

Portal warnings (must respect in demo/ops):

- Hackathon / **non-sensitive test data only**.
- Ports are **public**; Management Portal is **HTTP without TLS**.
- Storage is **not persistent** (restart/delete can wipe state).
- Container **keeps billing** until stopped/deleted; API-key block does **not** stop it.

Management Portal:  
`http://20.240.154.131:52773/csp/sys/%25CSP.Portal.Home.zen`

---

## 3. What we can / should do with IRIS

### Should do (aligned with pitch + challenge)

1. **FHIR R4 endpoint is configured** on the existing ACI instance; reproducible setup/check is `iris/setup_iris.py`.
2. **Use synthetic resources only on the public ACI.** Load supplied patient resources only inside an explicitly approved event/hospital environment with appropriate isolation, transport protection, access controls, and retention.
3. **Implement matching against IRIS-held facts**, not by shipping full charts to an external LLM:
   - Structured criteria ↔ FHIR search / SQL / ObjectScript or Embedded Python running within the hospital boundary. No Avicenna cloud fetching, even narrow fields.
   - Cloud LLM: structure **public trial criteria only**. Patient feature extraction and explanations run hospital-side; an EU-region external LLM is not automatically hospital-side or approved.
4. **Demo the privacy story**:
   - Show trial catalog + criteria structuring in Avicenna UI.
   - Show match results with criterion-level explanations.
   - Explicitly say: patient payload stayed on IRIS (hospital-side).
5. **Keep IRIS lean**: stop/delete ACI when idle; re-create from portal recipe if needed (state is ephemeral).

### Can do (useful, optional)

| Capability | Why |
|------------|-----|
| FHIR REST CRUD + search (`Patient`, `Condition`, `Observation`, `MedicationRequest`, …) | Standard hospital interoperability surface. |
| Bulk / batch load of FHIR bundles | Faster ingest of synthetic/anonymised packs. |
| Management Portal + FHIR Config UI | Create endpoint, auth settings, inspect repo. |
| `zpm "install fhir-server"` (IPM) | Fast Community path to `/fhir/r4`. |
| JDBC/ODBC/Python on port 1972 | Analytics / criteria SQL if not pure FHIR. |
| iris-fhir-template / Hackathon Kit containers | Local or alternate deploy with sample FHIR UI/Swagger if ACI setup is slow. |

### Should not do

- Put **real** health or personal data into this public ACI.
- Leave IRIS running overnight without need (Azure team budget).
- Treat IRIS as long-term durable storage (no persistence guarantee on this ACI recipe).
- Expose unauthenticated FHIR to the public internet for any non-demo data (portal already warns; for demo, lock down or use short-lived allow-unauthenticated only with synthetic data).
- Contradict the pitch by sending full patient records to external model providers “because it’s easier.”

### Suggested minimal architecture for the weekend

```text
[Trials: CT.gov / clinic list]
        │  LLM: structure inclusion/exclusion
        ▼
[Avicenna cloud: versioned trial criteria, no patient access]
        │  criteria pushed inward
        ▼
[Hospital-side IRIS + local matcher + clinician UI/alerts]
        ▲
[Approved event data ingestion inside the same boundary]

Public ACI demo: synthetic resources only.
No patient records, fields, scores, or explanations flow back to cloud.
```

Deliverable UX: patient → ranked trials + per-criterion met / not met / missing.

---

## 4. Practical IRIS setup checklist (no data details)

1. Open Management Portal as `_SYSTEM`.
2. Ensure IPM/ZPM available; install FHIR server package **or** create endpoint via **Health → FHIR Configuration → Server Configuration**.
3. Prefer FHIR **R4** (`HL7v40` metadata).
4. Note endpoint URL (common Community patterns):
   - `/fhir/r4`
   - `/csp/healthshare/<ns>/fhir/r4`
5. Verify: `GET …/metadata` returns CapabilityStatement.
6. For the public ACI, load synthetic resources only. The restricted ingestion report describes the approved-environment patient-data path.
7. Run the matching service and clinician UI inside the hospital boundary. Keep secrets in `.env`, not in Git; use a least-privilege application identity before ingestion.

If ACI FHIR setup is blocked, fall back to [iris-fhir-template](https://github.com/intersystems-community/iris-fhir-template) locally or on another container in `rg-team16`, same privacy narrative.

---

## 5. Documentation & references

### Official InterSystems

| Topic | URL |
|--------|-----|
| IRIS for Health docs (version picker) | https://docs.intersystems.com/irisforhealth.html |
| Latest IRIS for Health docbook home | https://docs.intersystems.com/irisforhealthlatest/csp/docbook/DocBook.UI.Page.cls |
| Installing a new FHIR server | https://docs.intersystems.com/irisforhealthlatest/csp/docbook/DocBook.UI.Page.cls?KEY=HXFHIRINS_server_install_new |
| FHIR Config REST API (listed on version pages) | Linked from https://docs.intersystems.com/irisforhealth.html |
| Community Edition via Docker | https://developer.intersystems.com/next-steps/get-intersystems-iris-community-with-docker/ |

### Community / templates (fast path)

| Topic | URL |
|--------|-----|
| iris-fhir-template (FHIR R4 + sample) | https://github.com/intersystems-community/iris-fhir-template |
| One-command `zpm "install fhir-server"` | https://community.intersystems.com/post/set-your-intersystems-fhir-server-one-command |
| FHIR AI Hackathon Kit — server setup | https://github.com/intersystems-community/FHIR-AI-Hackathon-Kit/blob/main/Tutorial/0-FHIR-server-setup.md |
| Official sample FHIR resource repository lab | https://github.com/intersystems/samples-FHIR-resource-repository |
| Swagger UI for IRIS FHIR | https://github.com/intersystems-community/Swagger-IRIS-FHIR |

### Rakathon / team notes

| Topic | Where |
|--------|--------|
| Pitch copy | `PRESENTATION.md` |
| Challenge mission | `MISSION.md` |
| Portal IRIS deploy recipe + warnings | `azure_data/Rakathon · Modely a data.html` (IRIS section) |
| Team credentials / RG / container name | local `.env` (`INTER_SYSTEMS_*`, `IRIS_PASSWORD`) |

### FHIR standard (for matching design)

| Topic | URL |
|--------|-----|
| HL7 FHIR R4 | https://hl7.org/fhir/R4/ |
| RESTful API | https://hl7.org/fhir/R4/http.html |
| Search | https://hl7.org/fhir/R4/search.html |

---

## 6. One-line summary

**Use IRIS as the hospital-side FHIR store, with matching, feature extraction, explanations, and clinician UI inside that same boundary. Avicenna cloud supplies trial criteria only; no patient fetching or patient-linked outputs. Public ACI contains synthetic data only.**
