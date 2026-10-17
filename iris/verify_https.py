"""Verify trusted TLS, FHIR authentication, and blocked plaintext ports."""
import base64
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from setup_iris import ROOT, config


def main():
    env = config()
    origin = env['IRIS_WEB_ORIGIN'].rstrip('/')
    host = urllib.parse.urlparse(origin).hostname
    if not origin.startswith('https://'):
        raise RuntimeError('HTTPS origin required')
    context = ssl.create_default_context(cafile=str(ROOT / env['IRIS_CA_FILE']))
    with socket.create_connection((host, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            print('Verified TLS:', tls.version())
            print('Certificate expires:', tls.getpeercert()['notAfter'])
    path = env.get('IRIS_FHIR_PATH', '/csp/healthshare/avicenna/fhir/r4')
    auth = base64.b64encode((env.get('IRIS_USERNAME', '_SYSTEM') + ':' + env['IRIS_PASSWORD']).encode()).decode()
    headers = {'Accept': 'application/fhir+json', 'Authorization': 'Basic ' + auth}
    # Disable redirects so credentials never follow an unexpected destination.
    from setup_iris import NoRedirect
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    with opener.open(urllib.request.Request(origin + path + '/metadata', headers=headers), timeout=60) as response:
        metadata = json.load(response)
        assert metadata['resourceType'] == 'CapabilityStatement'
        assert metadata['fhirVersion'] == '4.0.1'
        print('FHIR metadata: R4 4.0.1')
    try:
        opener.open(urllib.request.Request(origin + path + '/Patient?_count=1',
                    headers={'Accept': 'application/fhir+json'}), timeout=20)
    except urllib.error.HTTPError as error:
        assert error.code in (401, 403)
        print('Anonymous patient search denied:', error.code)
    else:
        raise RuntimeError('Anonymous patient access was not denied')
    for port in (80, 1972, 52773):
        try:
            connection = socket.create_connection((host, port), timeout=5)
        except (TimeoutError, ConnectionRefusedError, OSError):
            print(f'Public TCP {port}: unreachable')
        else:
            connection.close()
            raise RuntimeError(f'Unexpected public port reachable: {port}')
    print('HTTPS checks passed; no patient records read or uploaded.')


if __name__ == '__main__':
    main()
