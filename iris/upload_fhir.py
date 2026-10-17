"""Upload approved event FHIR transactions over verified HTTPS, without readback.

Checkpoint files are protected and Git-ignored. Console output contains no
patient identifiers, source text, or raw server error details.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request

from setup_iris import ROOT, config, NoRedirect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=0, help='Maximum new bundles; 0 means all')
    args = parser.parse_args()
    env = config()
    origin = env['IRIS_WEB_ORIGIN'].rstrip('/')
    if not origin.startswith('https://'):
        raise RuntimeError('Refusing to upload without HTTPS')
    url = origin + env['IRIS_FHIR_PATH']
    source = ROOT / 'data/rakathon-dataset/fhir/bundles.ndjson'
    private = ROOT / '.opencode-secrets/iris-upload'
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    private.chmod(0o700)
    checkpoint = private / 'checkpoint.json'
    failure = private / 'failure.json'
    digest = hashlib.sha256()
    with source.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    source_hash = digest.hexdigest()
    state = {'source_sha256': source_hash, 'destination': url, 'completed_bundles': 0,
             'completed_resources': 0, 'complete': False}
    if checkpoint.exists():
        state = json.loads(checkpoint.read_text())
        if state['source_sha256'] != source_hash or state['destination'] != url:
            raise RuntimeError('Checkpoint source/destination mismatch; manual review required')

    def save(path, data):
        temp = path.with_suffix('.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2)
        temp.chmod(0o600)
        temp.replace(path)

    context = ssl.create_default_context(cafile=str(ROOT / env['IRIS_CA_FILE']))
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    credentials = base64.b64encode(
        (env.get('IRIS_USERNAME', '_SYSTEM') + ':' + env['IRIS_PASSWORD']).encode()).decode()
    headers = {'Authorization': 'Basic ' + credentials, 'Content-Type': 'application/fhir+json',
               'Accept': 'application/fhir+json', 'Prefer': 'handling=strict'}
    processed = 0
    print('Starting HTTPS upload; already completed bundles:', state['completed_bundles'], flush=True)
    with source.open('rb') as stream:
        for index, raw in enumerate(stream, 1):
            if index <= state['completed_bundles']:
                continue
            bundle = json.loads(raw)
            entries = bundle.get('entry', [])
            if bundle.get('resourceType') != 'Bundle' or bundle.get('type') != 'transaction':
                raise RuntimeError(f'Invalid transaction structure at bundle index {index}')
            for entry in entries:
                resource = entry['resource']
                if entry.get('request') != {'method': 'PUT', 'url': resource['resourceType'] + '/' + resource['id']}:
                    raise RuntimeError(f'Non-idempotent request at bundle index {index}')
            for attempt in range(4):
                try:
                    req = urllib.request.Request(url, data=raw, headers=headers, method='POST')
                    with opener.open(req, timeout=300) as response:
                        result = json.load(response)
                    if result.get('resourceType') != 'Bundle' or result.get('type') != 'transaction-response':
                        raise RuntimeError('Unexpected transaction response')
                    statuses = [str(e.get('response', {}).get('status', '')).split(' ', 1)[0]
                                for e in result.get('entry', [])]
                    if len(statuses) != len(entries) or any(s not in ('200', '201', '204') for s in statuses):
                        save(failure, {'bundle_index': index, 'reason': 'transaction response mismatch',
                                       'statuses': statuses})
                        raise RuntimeError(f'Transaction failed at bundle index {index}; protected checkpoint saved')
                    break
                except urllib.error.HTTPError as error:
                    # Never emit raw OperationOutcome diagnostics: they may contain PHI.
                    codes = []
                    try:
                        outcome = json.loads(error.read())
                        codes = [issue.get('code') for issue in outcome.get('issue', [])]
                    except (ValueError, OSError):
                        pass
                    save(failure, {'bundle_index': index, 'http_status': error.code,
                                   'issue_codes': codes, 'attempt': attempt + 1})
                    if error.code in (429, 502, 503, 504) and attempt < 3:
                        print('Temporary HTTP error; retrying same fixed-ID transaction:', error.code, flush=True)
                        time.sleep(2 ** (attempt + 1))
                        continue
                    raise RuntimeError(f'Upload stopped at bundle index {index}: HTTP {error.code}; no raw diagnostics logged') from None
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    save(failure, {'bundle_index': index, 'reason': 'uncertain network outcome',
                                   'attempt': attempt + 1})
                    if attempt < 3:
                        print('Uncertain network outcome; retrying fixed-ID transaction (may add history versions)', flush=True)
                        time.sleep(2 ** (attempt + 1))
                        continue
                    raise RuntimeError(f'Uncertain upload outcome at bundle index {index}; stopped for review') from None
            state['completed_bundles'] = index
            state['completed_resources'] += len(entries)
            save(checkpoint, state)
            processed += 1
            if processed == 1 or index % 10 == 0:
                print('Acknowledged bundles:', index, 'resources:', state['completed_resources'], flush=True)
            if args.limit and processed >= args.limit:
                print('Canary/limit reached; checkpoint saved. No patient readback performed.', flush=True)
                return
    state['complete'] = True
    save(checkpoint, state)
    print('Upload complete. Acknowledged bundles:', state['completed_bundles'],
          'resources:', state['completed_resources'], 'No patient readback performed.', flush=True)


if __name__ == '__main__':
    main()
