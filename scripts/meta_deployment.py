"""Deployment factories. Production remains disabled unless explicitly configured and enabled."""
import argparse
import os
import signal
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from app.integrations.meta_whatsapp import Bridge, create_app
from app.integrations.meta_runtime import Worker
from scripts.meta_worker import SyntheticSender


def configuration(role="check"):
    if os.getenv("META_DEPLOYMENT_MODE", "disabled") == "production":
        from app.integrations.meta_production import configuration as production
        return production(role)
    mode = os.getenv('META_DEPLOYMENT_MODE', 'disabled')
    if mode not in ('disabled', 'simulation'):
        raise ValueError('Live activation is not available; use disabled or simulation')
    if any(os.getenv(k, 'false').lower() != 'false' for k in
           ('META_LIVE_SEND_ENABLED', 'WHATSAPP_ADAPTER_ENABLED')):
        raise ValueError('Legacy/live enable flags must remain false')
    if mode == 'disabled':
        return {'mode': mode}
    root = Path(os.environ['META_SIMULATION_ROOT']).resolve()
    if not root.is_dir() or (root / '.simulation-only').read_text().strip() != 'simulation-only-v1':
        raise ValueError('An explicit isolated simulation directory is required')
    # Never use the host application database or its .env through the simulation entry point.
    if os.getenv('APP_ENV') != 'test' or os.getenv('DATABASE_URL') != 'sqlite:///' + str(root / 'business.sqlite3'):
        raise ValueError('Simulation requires APP_ENV=test and its own business database')
    url = os.getenv('META_ADAPTER_URL', 'http://adapter:8011')
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('adapter', '127.0.0.1') or
            parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Adapter URL must be a private, fixed HTTP endpoint')
    return {'mode': mode, 'root': root, 'url': url,
            'secret': 'simulation-only-deployment-signing-' + 'x'*32,
            'app_secret': 'simulation-only-meta-app-' + 'x'*32,
            'verify_token': 'simulation-only-verification-' + 'x'*32}


def adapter_app():
    config = configuration('adapter')
    from app.integrations.whatsapp import create_app as adapter_factory
    if config['mode'] == 'disabled' or (config['mode'] == 'production' and not config['enabled']):
        return adapter_factory()
    if config['mode'] == 'production':
        return adapter_factory(enabled=True, signing_secret=config['secret'], provider_id=config['provider'],
                               recipient_id=config['recipient'], state_path=config['adapter_state'], pilot_required=True)
    return adapter_factory(enabled=True, signing_secret=config['secret'],
                           state_path=config['root'] / 'adapter.sqlite3')


def bridge(config, adapter, *, transport=None):
    if config["mode"] == "production":
        from app.integrations.meta_delivery import GraphSender
        sender = GraphSender(phone_number_id=config["recipient"], api_version=config["version"],
                             token=config.get("token", ""), enabled=config["sending"] and config["role"] == "worker",
                             transport=transport)
        return Bridge(state_path=config["bridge_state"], adapter=adapter, sender=sender,
                      channel_secret=config["secret"], provider_id=config["provider"], recipient_id=config["recipient"])
    return Bridge(state_path=config['root'] / 'bridge.sqlite3', adapter=adapter,
                  sender=SyntheticSender(), channel_secret=config['secret'])


def http_adapter(config):
    # No proxy inheritance, redirects or retries; credentials never leave the private route.
    return httpx.Client(base_url=config['url'], timeout=httpx.Timeout(10, connect=3),
                        follow_redirects=False, trust_env=False)


def webhook_app():
    config = configuration('webhook')
    if config['mode'] == 'disabled' or (config['mode'] == 'production' and not config['enabled']):
        return create_app()
    # Webhook only persists messages. It does not need an HTTP connection or sender token.
    return create_app(enabled=True, bridge=bridge(config, None),
                      app_secret=config['app_secret'], verify_token=config['verify_token'],
                      waba_id=config.get('waba_id', 'simulation-waba'), phone_number_id=config.get('recipient', 'simulation-line'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=['worker', 'check'])
    args = parser.parse_args(argv)
    config = configuration(args.role)
    if args.role == 'check':
        print('configuration=' + config['mode'] + '; checked=true; worker_started=false')
        return
    if config['mode'] == 'disabled' or (config['mode'] == 'production' and not (config['enabled'] and config['sending'])):
        print('Worker disabled; no queue opened and no network calls')
        return
    with http_adapter(config) as adapter:
        worker = Worker(bridge(config, adapter))
        previous = {s: signal.signal(s, worker.request_stop) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            worker.run()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    main()
