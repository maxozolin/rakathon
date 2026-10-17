"""Generate private-CA TLS material and an HTTPS-only ACI deployment.

No patient files are read. Deployment secrets/private keys remain Git-ignored.
Run with --apply to update the existing group (may clear ephemeral IRIS state).
"""
import argparse
import base64
import json
from pathlib import Path
import secrets
import subprocess

from setup_iris import ROOT, config


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    env = config()
    group = env.get('INTER_SYSTEMS_GROUP', 'rg-team16')
    name = env.get('INTER_SYSTEMS_CONTAINER_NAME', 'aci-irishealth-team16')
    private = ROOT / '.opencode-secrets' / 'iris-tls'
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    private.chmod(0o700)
    snapshot = private / 'original-container.json'
    if snapshot.exists():
        current = json.loads(snapshot.read_text())
    else:
        current = json.loads(run(['az', 'container', 'show', '-g', group, '-n', name, '-o', 'json']))
        snapshot.write_text(json.dumps(current, indent=2) + '\n')
        snapshot.chmod(0o600)
    public = ROOT / 'iris' / 'tls'
    public.mkdir(exist_ok=True)
    settings_path = private / 'settings.json'
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        label = 'avicenna-team16-' + secrets.token_hex(4)
        settings = {'dns_label': label,
                    'hostname': f"{label}.{current['location']}.azurecontainer.io"}
        settings_path.write_text(json.dumps(settings, indent=2) + '\n')
        settings_path.chmod(0o600)
    hostname = settings['hostname']
    ca = public / 'avicenna-event-ca.crt'
    if not ca.exists():
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes',
             '-keyout', str(private / 'ca.key'), '-out', str(ca), '-days', '30',
             '-sha256', '-subj', '/CN=Avicenna Event Private CA',
             '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
             '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
        run(['openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes',
             '-keyout', str(private / 'server.key'), '-out', str(private / 'server.csr'),
             '-subj', f'/CN={hostname}'])
        extensions = private / 'server.ext'
        extensions.write_text(
            f'subjectAltName=DNS:{hostname}\n'
            'basicConstraints=critical,CA:FALSE\n'
            'keyUsage=critical,digitalSignature,keyEncipherment\n'
            'extendedKeyUsage=serverAuth\n')
        run(['openssl', 'x509', '-req', '-in', str(private / 'server.csr'),
             '-CA', str(ca), '-CAkey', str(private / 'ca.key'), '-CAcreateserial',
             '-CAserial', str(private / 'ca.srl'), '-out', str(private / 'server.crt'),
             '-days', '7', '-sha256', '-extfile', str(extensions)])
    run(['openssl', 'verify', '-CAfile', str(ca), '-verify_hostname', hostname,
         str(private / 'server.crt')])
    caddyfile = f'''{{
    admin off
    auto_https off
}}
https://{hostname} {{
    tls /mnt/tls/server.crt /mnt/tls/server.key
    reverse_proxy 127.0.0.1:52773
}}
'''
    # Bootstrap inside the container, avoiding publicly exposed native DB ports.
    # Terminal brace blocks must occupy one physical line.
    setup = '''try { if '##class(%SYS.Namespace).Exists("AVICENNA") { do ##class(HS.Util.Installer.Foundation).Install("AVICENNA") } } catch exception { write exception.DisplayString(),! halt 1 }
zn "AVICENNA"
try { do ##class(HS.FHIRServer.Installer).InstallNamespace() do ##class(HS.FHIRMeta.Impl.Base).bootstrap(1) set metadata=##class(HS.FHIRMeta.Impl.Base).getInstance($lb("hl7.fhir.r4.core@4.0.1")) do metadata.Load() if '##class(HS.FHIRServer.ServiceAdmin).EndpointExists("/csp/healthshare/avicenna/fhir/r4") { do ##class(HS.FHIRServer.Installer).InstallInstance("/csp/healthshare/avicenna/fhir/r4","HS.FHIRServer.Storage.JsonAdvSQL.InteractionsStrategy",$lb("hl7.fhir.r4.core@4.0.1")) } } catch exception { write exception.DisplayString(),! halt 1 }
halt
'''
    bootstrap = '#!/bin/sh\nset -eu\niris session IRIS -U HSLIB < /mnt/bootstrap/setup.script\n'
    encode = lambda value: base64.b64encode(value.encode()).decode()
    iris_container = current['containers'][0]
    deployment = {
        'apiVersion': '2023-05-01', 'name': name, 'location': current['location'],
        'type': 'Microsoft.ContainerInstance/containerGroups',
        'tags': current.get('tags') or {},
        'properties': {
            'osType': 'Linux', 'restartPolicy': current.get('restartPolicy', 'Never'),
            'containers': [
                {'name': iris_container['name'], 'properties': {
                    'image': iris_container['image'],
                    'command': ['/iris-main', '--password-file', '/mnt/secrets/iris-password',
                                '--after', 'sh /mnt/bootstrap/bootstrap.sh'],
                    'resources': {'requests': {'cpu': 2, 'memoryInGB': 2}},
                    'ports': [{'port': 52773, 'protocol': 'TCP'}],
                    'volumeMounts': [{'name': 'secrets', 'mountPath': '/mnt/secrets', 'readOnly': True},
                                     {'name': 'bootstrap', 'mountPath': '/mnt/bootstrap', 'readOnly': True}],
                }},
                {'name': 'https-proxy', 'properties': {
                    'image': 'caddy:2.10.2-alpine',
                    'command': ['caddy', 'run', '--config', '/mnt/tls/Caddyfile', '--adapter', 'caddyfile'],
                    'resources': {'requests': {'cpu': 0.5, 'memoryInGB': 0.5}},
                    'ports': [{'port': 443, 'protocol': 'TCP'}],
                    'volumeMounts': [{'name': 'tls', 'mountPath': '/mnt/tls', 'readOnly': True}],
                }},
            ],
            'ipAddress': {'type': 'Public', 'dnsNameLabel': settings['dns_label'],
                          'ports': [{'port': 443, 'protocol': 'TCP'}]},
            'volumes': [
                {'name': 'secrets', 'secret': {'iris-password': encode(env['IRIS_PASSWORD'])}},
                {'name': 'bootstrap', 'secret': {'bootstrap.sh': encode(bootstrap), 'setup.script': encode(setup)}},
                {'name': 'tls', 'secret': {'server.key': encode((private / 'server.key').read_text()),
                                         'server.crt': encode((private / 'server.crt').read_text()),
                                         'Caddyfile': encode(caddyfile)}},
            ],
        },
    }
    path = private / 'deployment.json'
    path.write_text(json.dumps(deployment, indent=2) + '\n')
    for p in private.iterdir():
        if p.is_file():
            p.chmod(0o600)
    print('HTTPS hostname:', hostname)
    print('Client CA certificate:', ca.relative_to(ROOT))
    print(run(['openssl', 'x509', '-in', str(ca), '-noout', '-fingerprint', '-sha256']).strip())
    print('Public ports: 443 only; group allocation: 2.5 CPU / 2.5 GiB')
    print('Generated secret deployment:', path.relative_to(ROOT))
    if args.apply:
        subprocess.run(['az', 'container', 'create', '-g', group, '-f', str(path),
                        '--only-show-errors', '-o', 'none'], check=True)
        print('Azure deployment submitted successfully')


if __name__ == '__main__':
    main()
