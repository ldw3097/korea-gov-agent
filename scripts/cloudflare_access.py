"""Targeted Access API operations. Secrets and API response bodies never go to stdout."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import shlex
import subprocess

import httpx

from operator_config import ROOT, load_config, require_setting

PRIVATE = ROOT / '.private' / 'cloudflare'


def save(name, value):
    PRIVATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = PRIVATE / name
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
    path.chmod(0o600)
    return path


def api(client, method, path, body=None):
    response = client.request(method, path, json=body)
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError('Cloudflare response format error') from None
    if response.is_error or not data.get('success'):
        codes = [e.get('code') for e in data.get('errors', [])]
        raise RuntimeError(f'Cloudflare API failed: HTTP {response.status_code}, codes {codes}')
    return data.get('result')


def discover(ssh_target):
    # Read only existing deployment metadata. No token or email is returned over stdout.
    # Tunnel token exists in cloudflared, not the web process.
    # cloudflared is distroless; inspect using server-side Python instead of an exec shell.
    remote_code = '''import json,subprocess,base64
r=subprocess.run(['sudo','-n','docker','inspect','lh-agent-poc-cloudflared-1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
c=json.loads(r.stdout)[0]
env=dict(v.split('=',1) for v in c['Config']['Env'])
t=env['TUNNEL_TOKEN']
d=json.loads(base64.b64decode(t+'='*(-len(t)%4)))
print(json.dumps({'account_id':d['a']}))
'''
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '--', ssh_target, 'python3 -c ' + shlex.quote(remote_code)],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return json.loads(result.stdout)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'create-google', 'configure-app', 'verify', 'revoke'])
    args = parser.parse_args()
    config = load_config()
    token = require_setting(config, 'cloudflare_api_token')
    hostname = require_setting(config, 'access_hostname')
    if not re.fullmatch(r'[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+', hostname):
        raise SystemExit('Set access_hostname to the Access app hostname without a scheme or path.')
    metadata_path = PRIVATE / 'metadata.json'
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    else:
        metadata = discover(require_setting(config, 'ssh_target'))
    with httpx.Client(base_url='https://api.cloudflare.com/client/v4/',
                      headers={'Authorization': 'Bearer ' + token}, timeout=20) as client:
        verified = api(client, 'GET', 'user/tokens/verify')
        if verified['status'] != 'active':
            raise RuntimeError('Cloudflare API token is not active')
        prefix = 'accounts/' + metadata['account_id'] + '/access/'
        apps = api(client, 'GET', prefix + 'apps?per_page=100')
        matching = [a for a in apps if a.get('domain') == hostname]
        if len(matching) != 1:
            raise RuntimeError('Expected exactly one Access app for the PoC hostname')
        app = api(client, 'GET', prefix + 'apps/' + matching[0]['id'])
        if metadata_path.exists() and (app['id'] != metadata['app_id'] or app['aud'] != metadata['audience']):
            raise RuntimeError('Access app does not match the saved app ID and audience.')
        policies = api(client, 'GET', prefix + 'apps/' + app['id'] + '/policies')
        providers = api(client, 'GET', prefix + 'identity_providers')
        if not metadata_path.exists():
            metadata.update(app_id=app['id'], audience=app['aud'])
            save('metadata.json', metadata)
        if args.action == 'inspect':
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
            save('snapshot-' + stamp + '.json', {'application': app, 'policies': policies, 'identity_providers': providers})
            print('Token active; target Access app located; application/policies/providers backed up privately.')
            print('Configured identity provider types: ' + ', '.join(p.get('type', '?') for p in providers))
            print('Target policy decisions: ' + ', '.join(p.get('decision', '?') for p in policies))
        elif args.action == 'create-google':
            candidates = [p for p in providers if p['name'] == 'LH PoC Google' and p['type'] == 'google']
            if not candidates:
                oauth = config.get('google_oauth')
                credential = oauth.get('web') if isinstance(oauth, dict) else None
                if not isinstance(credential, dict):
                    raise SystemExit('Set google_oauth.web in .private/operator.json.')
                client_id = require_setting(credential, 'client_id')
                client_secret = require_setting(credential, 'client_secret')
                provider = api(client, 'POST', prefix + 'identity_providers', {
                    'name': 'LH PoC Google', 'type': 'google',
                    'config': {'client_id': client_id, 'client_secret': client_secret},
                })
            elif len(candidates) == 1:
                provider = candidates[0]
            else:
                raise RuntimeError('Ambiguous Google provider')
            if not (PRIVATE / 'google-provider.json').exists():
                save('google-provider.json', {'id': provider['id']})
            print('Dedicated Google provider ready. No Access application policy changed.')
        elif args.action == 'configure-app':
            provider_id = json.loads((PRIVATE / 'google-provider.json').read_text())['id']
            # Update only the target application, never a shared policy in place.
            body = {k: v for k, v in app.items() if k in (
                'name', 'domain', 'type', 'session_duration', 'app_launcher_visible', 'logo_url',
                'custom_deny_url', 'custom_deny_message', 'custom_non_identity_deny_url',
                'cors_headers', 'self_hosted_domains', 'destinations', 'tags', 'http_only_cookie_attribute',
                'same_site_cookie_attribute', 'path_cookie_attribute', 'enable_binding_cookie',
                'options_preflight_bypass', 'service_auth_401_redirect')}
            body.update(allowed_idps=[provider_id], auto_redirect_to_identity=True,
                        policies=[{'name': 'LH PoC Google sign-in', 'decision': 'allow', 'precedence': 1,
                                   'include': [{'login_method': {'id': provider_id}}], 'require': [], 'exclude': []}])
            updated = api(client, 'PUT', prefix + 'apps/' + app['id'], body)
            if updated['aud'] != metadata['audience']:
                raise RuntimeError('Audience unexpectedly changed; restore saved app configuration')
            print('Target application now requires Google sign-in. No Bypass policy. Audience preserved.')
        elif args.action in ('verify', 'revoke'):
            provider_id = json.loads((PRIVATE / 'google-provider.json').read_text())['id']
            assert app['allowed_idps'] == [provider_id]
            assert app['auto_redirect_to_identity'] is True
            assert len(policies) == 1 and policies[0]['decision'] == 'allow'
            assert policies[0]['include'] == [{'login_method': {'id': provider_id}}]
            assert app['aud'] == metadata['audience']
            print('Verified: Google-only Allow, no Bypass, existing audience unchanged.')
            if args.action == 'revoke':
                api(client, 'POST', prefix + 'apps/' + app['id'] + '/revoke_tokens', {})
                print('Previous sessions for this application revoked; fresh Google sign-in required.')


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        # Keep untrusted provider responses and request bodies out of logs.
        if isinstance(error, RuntimeError):
            raise SystemExit(str(error)) from None
        raise SystemExit('Cloudflare operation failed; secret-bearing diagnostics suppressed.') from None
