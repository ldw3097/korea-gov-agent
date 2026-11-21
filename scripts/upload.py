"""Upload this PoC only; excludes secrets, development data, and legacy code."""
import subprocess
import tarfile
import tempfile

from operator_config import ROOT, load_config, require_setting

ssh_target = require_setting(load_config(), 'ssh_target')
files = [ROOT / name for name in ('compose.yaml', '.dockerignore', 'requirements.lock')]
for pattern in ('infra/Dockerfile', 'services/api/lh_agent/*.py', 'apps/web/*.html', 'apps/web/*.js', 'apps/web/*.css'):
    files.extend(ROOT.glob(pattern))
with tempfile.TemporaryFile() as bundle:
    with tarfile.open(fileobj=bundle, mode='w:gz') as archive:
        for path in files:
            info = archive.gettarinfo(str(path), arcname=str(path.relative_to(ROOT)))
            info.mode = 0o644
            with path.open('rb') as stream:
                archive.addfile(info, stream)
    bundle.seek(0)
    subprocess.run(['ssh', '-o', 'BatchMode=yes', '--', ssh_target,
                    'umask 077; mkdir -p "$HOME/lh-agent-poc" && tar --no-same-owner -xzf - -C "$HOME/lh-agent-poc"'],
                   stdin=bundle, check=True)
print('PoC source uploaded; no credentials or personal data transferred.')
