"""Fail-closed production configuration; secret values are never included in errors."""
import os
import re
import stat
from pathlib import Path


def flag(name):
    value = os.getenv(name, 'false')
    if value not in ('true', 'false'):
        raise ValueError(f'{name} must be true or false')
    return value == 'true'


def secret_file(name):
    if os.getenv(name):
        raise ValueError(f'{name}: plaintext environment credentials are forbidden')
    path = Path(os.getenv(name + '_FILE', ''))
    fd = None
    try:
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid not in (0, os.geteuid()) or stat.S_IMODE(info.st_mode) not in (0o400, 0o600)):
            raise ValueError()
        raw = os.read(fd, 8193)
        value = raw.decode('utf-8').rstrip('\r\n')
        if (not 32 <= len(value) <= 8192 or len(raw) > 8192 or
                any(c.isspace() or ord(c) < 33 for c in value) or
                any(word in value.lower() for word in ('replace', 'simulation', 'example', 'generate', 'placeholder'))):
            raise ValueError()
        return value
    except (OSError, ValueError, UnicodeError):
        raise ValueError(f'{name}_FILE: require a private regular file containing a valid secret') from None
    finally:
        if fd is not None:
            os.close(fd)


def state_path(name, default):
    path = Path(os.getenv(name, default))
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError(f'{name}: absolute non-symlink path required')
    parent = path.parent
    if not parent.is_dir() or parent.stat().st_uid != os.geteuid() or stat.S_IMODE(parent.stat().st_mode) != 0o700:
        raise ValueError(f'{name}: provision an owner-only 0700 directory first')
    if path.exists():
        st = path.stat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o600):
            raise ValueError(f'{name}: existing state must be an owner-only 0600 regular file')
    return path


def configuration(role):
    if role not in ('webhook', 'adapter', 'worker', 'check'):
        raise ValueError('Unknown deployment role')
    enabled = flag('META_CHANNEL_ENABLED')
    sending = flag('META_LIVE_SEND_ENABLED')
    if flag('WHATSAPP_ADAPTER_ENABLED') or (sending and not enabled):
        raise ValueError('Invalid legacy or independent sending enable flag')
    if os.getenv('APP_ENV') != 'production' or os.getenv('APP_DEBUG') != 'false':
        raise ValueError('Production requires APP_ENV=production and APP_DEBUG=false')
    # No secret/state access when disabled, including in an incompletely provisioned installation.
    config = {'mode': 'production', 'enabled': enabled, 'sending': sending, 'role': role}
    if not enabled and role != 'check':
        return config
    for key in ('META_WABA_ID', 'META_PHONE_NUMBER_ID'):
        if not re.fullmatch(r'[0-9]{1,30}', os.getenv(key, '')):
            raise ValueError(f'{key}: numeric account ID required')
    version = os.getenv('META_GRAPH_VERSION', '')
    if not re.fullmatch(r'v[0-9]+\.0', version):
        raise ValueError('META_GRAPH_VERSION: explicit supported version required')
    if os.getenv('META_ADAPTER_URL', 'http://adapter:8011') != 'http://adapter:8011':
        raise ValueError('Production adapter must use the fixed private service route')
    if Path(os.getenv('META_BRIDGE_STATE', '/state/bridge.sqlite3')).resolve() == Path(os.getenv('WHATSAPP_ADAPTER_STATE', '/adapter-state/channel.sqlite3')).resolve():
        raise ValueError('Bridge and adapter state must be distinct')
    config.update(waba_id=os.environ['META_WABA_ID'], recipient=os.environ['META_PHONE_NUMBER_ID'],
                  provider='meta-whatsapp', version=version, url='http://adapter:8011')
    if role in ('adapter', 'check'):
        # Business authentication remains owned by the existing backend settings.
        if not os.getenv('DATABASE_URL', '').startswith('postgresql+psycopg://'):
            raise ValueError('Production adapter requires the shared PostgreSQL database')
        config['adapter_state'] = state_path('WHATSAPP_ADAPTER_STATE', '/adapter-state/channel.sqlite3')
    if role in ('worker', 'webhook', 'check'):
        config['bridge_state'] = state_path('META_BRIDGE_STATE', '/state/bridge.sqlite3')
    if role == 'check' and config['bridge_state'] == config['adapter_state']:
        raise ValueError('Bridge and adapter state must be distinct')
    # Webhook Bridge requires a signing secret at construction, even though it only enqueues.
    config['secret'] = secret_file('WHATSAPP_SIGNING_SECRET')
    if role in ('webhook', 'check'):
        config['app_secret'] = secret_file('META_APP_SECRET')
        config['verify_token'] = secret_file('META_VERIFY_TOKEN')
    if role in ('worker', 'check'):
        config['token'] = secret_file('META_ACCESS_TOKEN')
    return config
