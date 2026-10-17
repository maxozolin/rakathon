# Avicenna mock-hospital IRIS

## Offline patient matching coverage audit

`iris/audit_patient_coverage.py` scans the local canonical individual FHIR bundles and lab table without network access. It emits owner-only aggregate JSON and candidate evidence pointers under `.opencode-secrets/patient-coverage/`. These contain protected information and are not for models without patient-data access. `iris/report_patient_coverage.py` renders the restricted report after the audit finishes. Do not run multiple audits concurrently against the same output directory.

Candidate coverage is not validated fact coverage or clinical eligibility. No patient narrative excerpts are emitted to the console or report. Synthetic regression tests can be run without patient-data access:

```bash
python3 -m unittest discover -s iris -p test_patient_coverage.py
```

The corrected audit completed and the restricted report was regenerated on 17 October 2026. BRCA and ER/PR regex false positives were corrected and synthetic regression tests passed. The results are finalized candidate-coverage counts, not clinically validated facts or extraction accuracy estimates.

## Approved event dataset upload (completed)

The user explicitly approved this destination and requested uploading the supplied dataset. The full canonical streaming import completed successfully: every transaction response was checked and acknowledged over verified HTTPS. No patient readback was performed. This establishes acknowledged import completion, not independent persisted-state reconciliation, clinical validation, or durable storage. Exact counts are retained in the protected checkpoint. Earlier synthetic-only/no-upload statements below describe the prior state and are superseded by this explicit authorization and upload status.

Importer: `iris/upload_fhir.py`. It reads one canonical NDJSON stream, uses fixed-ID transaction PUTs, checks every response status, sends `Prefer: handling=strict`, and stops on non-retryable failures without disabling validation. Protected, owner-only checkpoints are in `.opencode-secrets/iris-upload/`. Resume with `python3 iris/upload_fhir.py`; avoid concurrent importers. Network retries may add history versions.

The bootstrap `_SYSTEM` identity is used for this authorized import; a scoped runtime identity remains outstanding. HTTPS-only public access is not private-network isolation. Event retention/deletion rules apply to IRIS data, history, local checkpoints, logs, and backups. Storage remains ephemeral: do not restart/redeploy while relying on imported state.

## HTTPS deployment (verified 16 October 2026)

The original group was deleted with user approval because Azure rejected adding CPU/memory in place. Its configuration is saved in `.opencode-secrets/iris-original.yaml`. The replacement group is running, Azure provisioning succeeded, and client checks passed:

- Certificate chain and hostname verified using the event CA; TLS 1.3 negotiated.
- Authenticated FHIR metadata returns R4 `4.0.1`; namespace `AVICENNA`, endpoint enabled.
- Anonymous Patient search returns `401`.
- Public TCP ports 80, 1972, and 52773 are unreachable from this environment.
- Public IP is now `74.158.45.144`; use the hostname, not the old IP.
- No supplied patient resources loaded or fetched.

The initial startup script failed; FHIR metadata and endpoint were repaired through Azure container exec. The currently mounted startup script must be corrected before relying on restart/recreation. The server certificate expires **23 October 2026 at 21:23:33 UTC**.

Verified HTTPS base:
`https://avicenna-team16-373b9174.swedencentral.azurecontainer.io/csp/healthshare/avicenna/fhir/r4`

The replacement configuration exposes only TCP 443 and includes Caddy forwarding to IRIS over container-group loopback. Ports 80, 1972, and 52773 are not published. Total allocation: 2.5 CPU / 2.5 GiB. This is HTTPS-only **public access**, not private-subnet/VPN isolation. Credentials/private keys remain in Git-ignored `.opencode-secrets/`; Caddy access logging is not enabled.

Client trust certificate: `iris/tls/avicenna-event-ca.crt`. Verify its SHA-256 fingerprint through a trusted channel:
`00:64:AD:9C:A1:5E:41:91:BF:5D:BE:00:D9:DB:5E:50:E2:BE:F1:14:60:1B:ED:96:AF:62:58:83:B3:6C:C2:59`.

Trust only this event CA where needed, not by disabling TLS verification. The leaf certificate has a seven-day lifetime and the CA a thirty-day lifetime. Renew before expiry if the deployment remains in use. Keep the CA private key local; only the server key/certificate are mounted into the proxy.

Non-secret client settings are in `iris/connection.env`; password still comes from `.env`. Re-run verification with:

```bash
python3 iris/verify_https.py
python3 iris/setup_iris.py
```

For clients supporting an explicit CA bundle:

```bash
curl --cacert iris/tls/avicenna-event-ca.crt \
  -H 'Accept: application/fhir+json' \
  https://avicenna-team16-373b9174.swedencentral.azurecontainer.io/csp/healthshare/avicenna/fhir/r4/metadata
```

The curl request has no credentials, so authentication may deny it. Use an approved credential-loading mechanism for authenticated requests; do not paste passwords into command history. Browser clients require importing the public CA certificate into their appropriate trust store.

Bootstrap recreates the empty Foundation/R4 endpoint inside the IRIS container, avoiding public native DB access. `iris/deploy_https.py` prepares the certificate and deployment manifest; it never silently deletes an existing group. Azure resource-allocation changes require a separately authorized delete/recreate operation.

## Previous HTTP deployment (historical verification)

- Existing Azure container: `aci-irishealth-team16`, resource group `rg-team16`.
- IRIS for Health 2026.1 Build 235U; dedicated Foundation namespace `AVICENNA`.
- FHIR R4 base: `http://20.240.154.131:52773/csp/healthshare/avicenna/fhir/r4`.
- `GET /metadata` returns a `CapabilityStatement`, FHIR `4.0.1`.
- Unauthenticated `GET /Patient?_count=1` returns HTTP `401`.
- Endpoint is enabled with `debug_mode=0` and indexing errors not silenced.
- No source patient resources uploaded. No new Azure resource created.

**Synthetic data only:** this deployment has public, unencrypted HTTP/TCP ports and ephemeral storage. Basic authentication does not encrypt credentials. Authentication is verified, but this is not a GDPR-compliance or production-hardening certification. A least-privilege ingestion/matching account, TLS/private networking, and retention controls remain prerequisites for protected data.

## Reproduce / check

```bash
python3 -m venv iris/.venv
iris/.venv/bin/pip install -r iris/requirements.txt
iris/.venv/bin/python iris/setup_iris.py
# Only when recreating an empty demo installation:
iris/.venv/bin/python iris/setup_iris.py --apply
```

The script reads `IRIS_PASSWORD` from the root `.env` (or environment), defaults to `_SYSTEM`, and never reads `data/`. Optional settings: `IRIS_HOST`, `IRIS_WEB_ORIGIN`, `IRIS_USERNAME`, `IRIS_SUPERSERVER_PORT`, `IRIS_HOSPITAL_NAMESPACE`, `IRIS_FHIR_PATH`. Do not redirect it to a different host without verifying ownership and changing credentials. `_SYSTEM` is a bootstrap/check identity, not the intended runtime account.

Foundation activation must start in `HSLIB` on this image. It prepares FHIR metadata automatically. Endpoint creation uses the native FHIR management REST API; no IPM installation is necessary. Installation is asynchronous and may take several minutes. Re-running checks does not create another endpoint; `--apply` skips an existing matching URL.

The initial management API `default_prefer_handling` field was not retained by this image; importers should explicitly send `Prefer: handling=strict`. Never disable validation to force a problematic source bundle through.

## Required privacy architecture

Cloud trial criteria → hospital-side IRIS + matcher → hospital-side clinician UI.

The cloud must not fetch patient fields or receive patient-linked scores/explanations. A hospital-side service may use local SQL/FHIR access or Embedded Python. An EU-hosted external model is not automatically inside that boundary. This task configures the store, not the matching engine or UI.

For source-data loading and observed limitations, see the restricted report. Models without approved patient-data access should read only `reports/GENERAL_DATA_GUIDE.md`.

## Operations

The existing container continues to bill while running. No stop/restart/deletion was performed. Treat state as ephemeral; retain a reproducible configuration and an approved re-ingestion plan. Stop/delete via the team's authorized Azure procedure when the team is finished, not while other participants depend on it.
