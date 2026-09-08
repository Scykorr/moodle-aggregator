"""Optional real Docker/TLS/realm smoke test; owns only a random disposable project.

Requires Docker and openssl. Downloads the pinned images if absent. Creates no
students and never accesses the existing Moodle containers. Cleans up its own
containers and volume; downloaded images remain cached.
"""
import argparse
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import ROOT, generate
from probe import check_discovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openssl', default='openssl')
    args = parser.parse_args()
    project = 'identity-smoke-' + uuid.uuid4().hex[:12]
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0))
        port = port_socket.getsockname()[1]
    base = f'https://localhost:{port}'
    with tempfile.TemporaryDirectory(prefix=project + '-') as temporary:
        work = Path(temporary)
        shutil.copyfile(ROOT / 'compose.yml', work / 'compose.yml')
        generate({'realm': 'students', 'idp_url': base, 'bind_ip': '127.0.0.1',
                  'sites': [{'id': 'moodle-test', 'version': '4.5',
                             'url': 'https://moodle-test.invalid',
                             'ip': '127.0.0.1', 'subnet': '127.0.0.0/8'}]}, work / 'generated')
        certs = work / 'certs'
        certs.mkdir()
        openssl_config = work / 'openssl.cnf'
        openssl_config.write_text('[req]\ndistinguished_name=dn\n[dn]\n', encoding='ascii')
        certificate_result = subprocess.run([args.openssl, 'req', '-x509', '-newkey', 'rsa:2048',
                        '-config', str(openssl_config),
                        '-nodes', '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1',
                        '-keyout', str(certs / 'server.key'),
                        '-out', str(certs / 'server.crt')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if certificate_result.returncode:
            raise RuntimeError(certificate_result.stderr.decode(errors='replace'))
        # Disposable key only: production permissions are documented separately.
        (certs / 'server.key').chmod(0o644)
        command = ['docker', 'compose', '-p', project, '--env-file',
                   str(work / 'generated/.env'), '-f', str(work / 'compose.yml')]
        context = ssl.create_default_context(cafile=str(certs / 'server.crt'))

        def request(path, form=None, token=None):
            data = urllib.parse.urlencode(form).encode() if form else None
            headers = {'Authorization': 'Bearer ' + token} if token else {}
            req = urllib.request.Request(base + path, data=data, headers=headers)
            with urllib.request.urlopen(req, context=context, timeout=5) as response:
                return json.load(response)

        try:
            subprocess.run(command + ['config', '--quiet'], check=True)
            print('Compose validated; starting isolated identity server.', flush=True)
            subprocess.run(command + ['up', '-d', '--quiet-pull'], check=True, timeout=600)
            deadline = time.monotonic() + 180
            while True:
                try:
                    discovery = request('/realms/students/.well-known/openid-configuration')
                    break
                except (OSError, ValueError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Identity server did not become ready within 180 seconds')
                    time.sleep(2)
            check_discovery(discovery, base + '/realms/students')
            env = dict(line.split('=', 1) for line in
                       (work / 'generated/.env').read_text().splitlines())
            token = request('/realms/master/protocol/openid-connect/token', form={
                'client_id': 'admin-cli', 'grant_type': 'password',
                'username': 'bootstrap-admin', 'password': env['KC_BOOTSTRAP_ADMIN_PASSWORD'],
            })['access_token']
            realm = request('/admin/realms/students', token=token)
            assert realm['sslRequired'] == 'all' and not realm['registrationAllowed']
            clients = request('/admin/realms/students/clients?clientId=moodle-test', token=token)
            assert len(clients) == 1
            client = clients[0]
            assert client['redirectUris'] == ['https://moodle-test.invalid/admin/oauth2callback.php']
            assert not client['publicClient'] and not client['directAccessGrantsEnabled']
            assert {'profile', 'email'} <= set(client['defaultClientScopes'])
            secret = request('/admin/realms/students/clients/' + client['id'] + '/client-secret', token=token)
            imported = json.loads((work / 'generated/realm/students-realm.json').read_text())
            assert secret['value'] == imported['clients'][0]['secret']
            print('PASS: real TLS, discovery, realm import, callback, scopes and client secret.', flush=True)
        finally:
            # Only the project name generated in this invocation is ever removed.
            subprocess.run(command + ['down', '-v', '--remove-orphans'], check=True, timeout=120)


if __name__ == '__main__':
    main()
