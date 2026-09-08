import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prepare import ROOT, generate, validate
from probe import check_discovery


class FederationTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'sites.example.json').read_text(encoding='utf-8'))

    def test_rejects_unsupported_old_moodle(self):
        for version in ('3', '3.0', '3.2.9', '2.9', 'garbage'):
            with self.subTest(version=version):
                self.config['sites'][0]['version'] = version
                with self.assertRaises(ValueError):
                    validate(self.config)

    def test_rejects_unsafe_urls(self):
        for url in ('http://moodle.example', 'https://user:pass@moodle.example',
                    'https://moodle.example/*', 'https://moodle.example/?x=1',
                    'https://moodle.example/../admin', 'https://moodle.example:99999',
                    'https://moodle.example\nINJECT=value'):
            with self.subTest(url=url):
                self.config['sites'][0]['url'] = url
                with self.assertRaises(ValueError):
                    validate(self.config)

    def test_rejects_duplicate_client(self):
        self.config['sites'].append(copy.deepcopy(self.config['sites'][0]))
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_rejects_reserved_realm_and_clients(self):
        self.config['realm'] = 'master'
        with self.assertRaises(ValueError):
            validate(self.config)
        self.config['realm'] = 'students'
        self.config['sites'][0]['id'] = 'account'
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_rejects_duplicate_canonical_url(self):
        self.config['sites'][1]['url'] = self.config['sites'][0]['url'] + '/'
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_rejects_address_outside_subnet(self):
        self.config['sites'][0]['ip'] = '10.90.0.10'
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_rejects_mismatched_ip_url(self):
        self.config['sites'][0]['url'] = 'https://10.30.0.11'
        with self.assertRaises(ValueError):
            validate(self.config)

    def test_invalid_input_does_not_create_output(self):
        self.config['realm'] = '../../bad'
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'generated'
            with self.assertRaises(ValueError):
                generate(self.config, output)
            self.assertFalse(output.exists())

    def test_generated_clients_and_secrets_are_isolated(self):
        self.config['sites'][0]['url'] += '/learning'
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'generated'
            generate(self.config, output)
            realm = json.loads((output / 'realm/students-realm.json').read_text(encoding='utf-8'))
            clients = realm['clients']
            self.assertEqual(3, len({c['secret'] for c in clients}))
            self.assertTrue(all(len(c['secret']) >= 64 for c in clients))
            self.assertFalse(realm['registrationAllowed'])
            self.assertNotIn('users', realm)
            self.assertEqual(['https://moodle3.campus.example/learning/admin/oauth2callback.php'],
                             clients[0]['redirectUris'])
            self.assertTrue(all(not c['directAccessGrantsEnabled'] and not c['publicClient']
                                for c in clients))
            before = (output / '.env').read_bytes()
            with self.assertRaises(FileExistsError):
                generate(self.config, output)
            self.assertEqual(before, (output / '.env').read_bytes())

    def test_discovery_rejects_wrong_issuer_and_endpoint(self):
        issuer = 'https://sso.campus.example/realms/students'
        document = {'issuer': issuer, 'response_types_supported': ['code']}
        for key in ('authorization_endpoint', 'token_endpoint', 'userinfo_endpoint', 'jwks_uri'):
            document[key] = issuer + '/protocol/openid-connect/test'
        check_discovery(document, issuer)
        with self.assertRaises(ValueError):
            check_discovery(document, 'https://another.example/realms/students')
        document['token_endpoint'] = 'https://another.example/token'
        with self.assertRaises(ValueError):
            check_discovery(document, issuer)


if __name__ == '__main__':
    unittest.main()
