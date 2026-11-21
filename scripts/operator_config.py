"""Read the private configuration shared by the local deployment tools."""

import json
import os
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / '.private' / 'operator.json'


def load_config():
    try:
        fd = os.open(CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, encoding='utf-8') as stream:
            mode = os.fstat(stream.fileno()).st_mode
            if not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o600:
                raise SystemExit('Expected a private regular file (0600) at .private/operator.json.')
            config = json.load(stream)
    except (OSError, ValueError):
        raise SystemExit('Cannot read .private/operator.json. See docs/DEPLOYMENT.md.') from None
    if not isinstance(config, dict):
        raise SystemExit('Expected a JSON object in .private/operator.json.')
    return config


def require_setting(config, key):
    value = config.get(key)
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise SystemExit(f'Invalid or missing {key} in .private/operator.json.')
    return value
