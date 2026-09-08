"""Generate a new Keycloak realm and Moodle settings; never modify live services."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
IDENTIFIER = re.compile(r'[a-z][a-z0-9-]{0,47}\Z')
RESERVED_CLIENTS = {'account', 'account-console', 'admin-cli', 'broker',
                    'realm-management', 'security-admin-console'}


def https_url(value):
    if not isinstance(value, str) or not re.fullmatch(r'https://[A-Za-z0-9.:-]+(?:/[A-Za-z0-9_/-]+)?', value):
        raise ValueError('Use an HTTPS IPv4/DNS URL without credentials, query or fragment')
    url = urlsplit(value)
    if not url.hostname or url.port == 0 or '..' in url.path or '//' in url.path:
        raise ValueError('Invalid URL host, port or path')
    return value.rstrip('/')


def validate(config):
    if not isinstance(config, dict) or not IDENTIFIER.fullmatch(config.get('realm', '')):
        raise ValueError('realm must be a lowercase identifier')
    if config['realm'] == 'master':
        raise ValueError('The built-in master realm cannot be used for students')
    config['idp_url'] = https_url(config['idp_url'])
    if urlsplit(config['idp_url']).path:
        raise ValueError('idp_url must not have a path with this Compose template')
    bind = ipaddress.IPv4Address(config['bind_ip'])
    if bind.is_unspecified or bind.is_multicast:
        raise ValueError('bind_ip must be a specific local IPv4 address')
    if not isinstance(config.get('sites'), list) or not config['sites']:
        raise ValueError('At least one Moodle site is required')
    ids, urls = set(), {config['idp_url']}
    for site in config['sites']:
        name = site['id']
        if not IDENTIFIER.fullmatch(name) or name in ids or name in RESERVED_CLIENTS:
            raise ValueError('Site identifiers must be unique lowercase identifiers')
        version = re.fullmatch(r'(3|4|5)\.(\d+)(?:\.\d+)?', site['version'])
        if not version or (version[1] == '3' and int(version[2]) < 3):
            raise ValueError('Core OAuth2 template requires Moodle 3.3+, 4.x or 5.x')
        site['url'] = https_url(site['url'])
        if site['url'] in urls:
            raise ValueError('Site URLs must be unique and different from idp_url')
        address = ipaddress.IPv4Address(site['ip'])
        subnet = ipaddress.IPv4Network(site['subnet'], strict=True)
        if address not in subnet or (subnet.prefixlen < 31 and address in (subnet.network_address, subnet.broadcast_address)):
            raise ValueError(f'{name}: IP is not a usable host in the declared subnet')
        host = urlsplit(site['url']).hostname
        try:
            literal_ip = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            literal_ip = None
        if literal_ip is not None and literal_ip != address:
            raise ValueError(f'{name}: URL IP differs from inventory IP')
        ids.add(name)
        urls.add(site['url'])
    return config


def write_private(path, text):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    if os.name != 'nt':
        path.chmod(0o600)


def generate(config, output):
    config = validate(config)
    # Refuse reruns: silently rotating a client secret breaks a running Moodle.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    realm_dir = output / 'realm'
    realm_dir.mkdir()
    issuer = config['idp_url'] + '/realms/' + config['realm']
    realm = {
        'realm': config['realm'], 'enabled': True, 'sslRequired': 'all',
        'registrationAllowed': False, 'resetPasswordAllowed': True,
        'editUsernameAllowed': False, 'duplicateEmailsAllowed': False,
        'verifyEmail': True, 'bruteForceProtected': True,
        'ssoSessionIdleTimeout': 1800, 'ssoSessionMaxLifespan': 28800,
        'clients': [],
    }
    instructions = [
        '# Локальные настройки Moodle — СОДЕРЖАТ СЕКРЕТЫ', '',
        f'Issuer / Service base URL: `{issuer}`',
        f'Discovery: `{issuer}/.well-known/openid-configuration`',
        'Scopes (login и offline): `openid profile email`.',
        'OAuth 2 core; callback не подходит для auth_oidc или SAML.',
        'User mappings: sub → username; given_name → firstname; family_name → lastname; email → email.',
        'sub — постоянный идентификатор привязки; не заменять на изменяемый email.', '',
    ]
    for site in config['sites']:
        secret = secrets.token_urlsafe(48)
        callback = site['url'] + '/admin/oauth2callback.php'
        realm['clients'].append({
            'clientId': site['id'], 'name': site['id'], 'enabled': True,
            'protocol': 'openid-connect', 'publicClient': False,
            'clientAuthenticatorType': 'client-secret', 'secret': secret,
            'standardFlowEnabled': True, 'implicitFlowEnabled': False,
            'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': False,
            'redirectUris': [callback], 'webOrigins': [],
            'fullScopeAllowed': False,
            'defaultClientScopes': ['profile', 'email'],
        })
        instructions += [f"## {site['id']} / Moodle {site['version']}", '',
                         f"Сайт: {site['url']}", f"Client ID: `{site['id']}`",
                         f'Client secret: `{secret}`', f'Redirect URI: `{callback}`', '']
    port = urlsplit(config['idp_url']).port or 443
    write_private(output / '.env',
                  f"IDP_URL={config['idp_url']}\nIDP_BIND_IP={config['bind_ip']}\n"
                  f'IDP_HTTPS_PORT={port}\nKC_DB_PASSWORD={secrets.token_urlsafe(48)}\n'
                  f'KC_BOOTSTRAP_ADMIN_PASSWORD={secrets.token_urlsafe(48)}\n')
    realm_file = realm_dir / (config['realm'] + '-realm.json')
    write_private(realm_file, json.dumps(realm, ensure_ascii=False, indent=2) + '\n')
    # No user passwords in realm exports. Keycloak must read this bind mount as UID 1000.
    # Restrict the parent output directory on the host, allow container read on Linux.
    if os.name != 'nt':
        realm_file.chmod(0o644)
    write_private(output / 'moodle-settings.md', '\n'.join(instructions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'sites.json')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    try:
        config = validate(json.loads(args.config.read_text(encoding='utf-8-sig')))
        if args.validate_only:
            print(f"Valid inventory: {len(config['sites'])} sites")
        else:
            generate(config, ROOT / 'generated')
            print('Created generated/.env, realm and moodle-settings.md (secrets not printed).')
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f'Cannot prepare federation: {exc}\n')


if __name__ == '__main__':
    main()
