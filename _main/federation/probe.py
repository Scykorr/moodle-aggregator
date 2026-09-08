"""Read-only DNS, TLS and OIDC discovery checks from the current machine."""
import argparse
import json
from pathlib import Path
import socket
import ssl
import urllib.request
from urllib.parse import urlsplit

from prepare import ROOT, validate


def check_discovery(document, issuer):
    if document.get('issuer') != issuer:
        raise ValueError('Discovery issuer does not match the canonical URL')
    for key in ('authorization_endpoint', 'token_endpoint', 'userinfo_endpoint', 'jwks_uri'):
        endpoint = document.get(key, '')
        if not isinstance(endpoint, str) or not endpoint.startswith(issuer + '/'):
            raise ValueError(f'Discovery {key} is missing or outside the configured issuer')
    if 'code' not in document.get('response_types_supported', []):
        raise ValueError('Authorization Code flow is not advertised')


def check_host(url, expected_ip, context, timeout):
    parsed = urlsplit(url)
    addresses = {item[4][0] for item in socket.getaddrinfo(
        parsed.hostname, parsed.port or 443, socket.AF_INET, socket.SOCK_STREAM)}
    if expected_ip not in addresses:
        raise ValueError('DNS does not include the IP declared in inventory')
    with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=parsed.hostname):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'sites.json')
    parser.add_argument('--ca', type=Path, help='PEM bundle for the internal certificate authority')
    parser.add_argument('--timeout', type=float, default=5)
    args = parser.parse_args()
    try:
        if not 0 < args.timeout <= 60:
            raise ValueError('timeout must be between 0 and 60 seconds')
        config = validate(json.loads(args.config.read_text(encoding='utf-8-sig')))
        context = ssl.create_default_context(cafile=str(args.ca) if args.ca else None)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Configuration error: {exc}\n')
    errors = 0
    targets = [('keycloak', config['idp_url'], config['bind_ip'])]
    targets += [(s['id'], s['url'], s['ip']) for s in config['sites']]
    for name, url, expected_ip in targets:
        try:
            check_host(url, expected_ip, context, args.timeout)
            print(f'OK {name}: DNS and TLS')
        except (OSError, ValueError) as exc:
            errors += 1
            print(f'FAIL {name}: {exc}')
    issuer = config['idp_url'] + '/realms/' + config['realm']
    try:
        with urllib.request.urlopen(issuer + '/.well-known/openid-configuration',
                                    context=context, timeout=args.timeout) as response:
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Discovery document exceeds 1 MiB')
            check_discovery(json.loads(data), issuer)
        print('OK keycloak: discovery and issuer')
    except (OSError, ValueError, AttributeError) as exc:
        errors += 1
        print(f'FAIL discovery: {exc}')
    print('This checks connectivity only, not user login, roles or active Moodle sessions.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
