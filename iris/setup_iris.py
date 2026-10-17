"""Configure an empty hackathon FHIR endpoint; never reads patient files.

Requires intersystems-irispython==5.4.1. Credentials stay in the local .env.
The existing public HTTP/TCP deployment is suitable for synthetic data only.
"""
import argparse
import base64
import json
import os
import ssl
from pathlib import Path
import time
import urllib.error
import urllib.request
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]


def config():
    values = {}
    for path in (ROOT / '.env', ROOT / 'iris' / 'connection.env'):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"\'')
    values.update(os.environ)
    return values


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create namespace and endpoint')
    args = parser.parse_args()
    env = config()
    host = env.get('IRIS_HOST', '20.240.154.131')
    origin = env.get('IRIS_WEB_ORIGIN', f'http://{host}:52773').rstrip('/')
    namespace = env.get('IRIS_HOSPITAL_NAMESPACE', 'AVICENNA')
    path = env.get('IRIS_FHIR_PATH', '/csp/healthshare/avicenna/fhir/r4')
    user = env.get('IRIS_USERNAME', '_SYSTEM')
    headers = {'Authorization': 'Basic ' + base64.b64encode(
        f"{user}:{env['IRIS_PASSWORD']}".encode()).decode(),
        'Content-Type': 'application/json', 'Accept': 'application/fhir+json, application/json'}
    ca_file = env.get('IRIS_CA_FILE')
    context = ssl.create_default_context(cafile=str(ROOT / ca_file) if ca_file else None)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def request(route, payload=None, authenticated=True):
        req = urllib.request.Request(origin + route,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers if authenticated else {'Accept': 'application/fhir+json'})
        try:
            response = opener.open(req, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            return response.code, dict(response.headers), body

    api = '/csp/fhir-management/api'
    code, _, info = request(api + '/namespaces')
    if code != 200:
        raise RuntimeError(f'Namespace discovery failed: HTTP {code}')
    print('FHIR namespaces:', [item['name'] for item in info])
    if args.apply and namespace not in [item['name'] for item in info]:
        import iris
        connection = iris.connect(host, int(env.get('IRIS_SUPERSERVER_PORT', '1972')),
                                  'HSLIB', user, env['IRIS_PASSWORD'])
        try:
            native = iris.createIRIS(connection)
            # Create a dedicated Foundation namespace, leaving USER untouched.
            native.classMethodVoid('HS.Util.Installer.Foundation', 'Install', namespace)
            print('Foundation namespace installed:', namespace)
            # Foundation.Install also prepares FHIR in IRIS for Health 2026.1.
            print('FHIR namespace prepared by Foundation installer:', namespace)
        finally:
            connection.close()
    query = '?namespace=' + urllib.parse.quote(namespace)
    def endpoint_exists(items):
        return any(item.get('endpoint', item).get('url') == path for item in items)

    code, _, endpoints = request(api + '/endpoints' + query)
    if code != 200:
        raise RuntimeError(f'Endpoint discovery failed: HTTP {code}')
    if args.apply and not endpoint_exists(endpoints):
        payload = {
            'name': 'Avicenna mock hospital R4 (synthetic only)',
            'url': path,
            'service_config_data': {
                'fhir_metadata_set': 'hl7.fhir.r4.core@4.0.1',
                'interactions_strategy_class': 'HS.FHIRServer.Storage.JsonAdvSQL.InteractionsStrategy',
                'debug_mode': 0,
                'default_prefer_handling': 'strict',
            },
            'strategy_config_data': {'silence_index_errors': False},
        }
        code, response_headers, job = request(api + '/endpoints' + query, payload)
        if code != 303:
            raise RuntimeError(f'Endpoint creation failed: HTTP {code}; {job}')
    if args.apply:
        for _ in range(100):
            code, _, jobs = request(api + '/jobs' + query)
            if code != 200:
                raise RuntimeError(f'Job discovery failed: HTTP {code}')
            relevant = [job for job in jobs if job.get('method') == 'AddEndpoint']
            running = [job for job in relevant if job.get('status') == 'running']
            if not running:
                break
            print('Endpoint installation is running')
            time.sleep(3)
        else:
            raise RuntimeError('Installation still running; rerun check later')
    code, _, metadata = request(path + '/metadata')
    if code != 200 or not metadata or metadata.get('resourceType') != 'CapabilityStatement':
        raise RuntimeError(f'FHIR metadata check failed: HTTP {code}')
    code, _, endpoints = request(api + '/endpoints' + query)
    endpoint = next(item.get('endpoint', item) for item in endpoints
                    if item.get('endpoint', item).get('url') == path)
    print('Endpoint enabled:', endpoint.get('enabled'))
    print('FHIR endpoint:', origin + path)
    print('FHIR version:', metadata.get('fhirVersion'))
    code, _, _ = request(path + '/Patient?_count=1', authenticated=False)
    print('Unauthenticated Patient search HTTP status:', code)
    if code not in (401, 403):
        raise RuntimeError('Unauthenticated access not denied; do not load any data')
    print('Verified: R4 metadata and authentication. No patient data loaded.')


if __name__ == '__main__':
    main()
