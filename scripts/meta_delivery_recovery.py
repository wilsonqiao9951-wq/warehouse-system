"""Local operator CLI. Inspect first, then explicitly confirm a state-specific action.
No API credentials, network requests, worker startup or sends occur here.
"""
import argparse
import json
from pathlib import Path

from app.integrations.meta_whatsapp import StateStore
from app.integrations.meta_delivery import DeliveryLifecycle


class LocalRecovery(StateStore, DeliveryLifecycle):
    def __init__(self, path):
        if not Path(path).is_file():
            raise ValueError('Existing private bridge state file required')
        super().__init__(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--id')
    parser.add_argument('--events', action='store_true')
    parser.add_argument('--action', choices=['inspect', 'cancel', 'retry'], default='inspect')
    parser.add_argument('--operator', default='')
    parser.add_argument('--reason', default='')
    parser.add_argument('--confirmation', default='')
    parser.add_argument('--accept-duplicate-risk', action='store_true')
    args = parser.parse_args(argv)
    try:
        store = LocalRecovery(args.state)
        if args.events and args.action != 'inspect':
            raise ValueError('Events inspection cannot mutate state')
        if args.action != 'inspect':
            if not args.id:
                raise ValueError('Message ID required')
            store.recover(args.id, action=args.action, operator=args.operator, reason=args.reason,
                          confirmation=args.confirmation, accept_duplicate_risk=args.accept_duplicate_risk)
        print(json.dumps(store.inspect_events() if args.events else store.inspect_delivery(args.id), indent=2, ensure_ascii=False))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
