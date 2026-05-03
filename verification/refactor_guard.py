import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app


DEFAULT_BASELINE = Path('verification/route_baseline.json')


def collect_route_map(flask_app):
    routes = []
    for rule in flask_app.url_map.iter_rules():
        if rule.endpoint == 'static':
            continue
        methods = sorted(m for m in rule.methods if m not in {'HEAD', 'OPTIONS'})
        routes.append(
            {
                'endpoint': rule.endpoint,
                'rule': rule.rule,
                'methods': methods,
            }
        )

    routes.sort(key=lambda row: (row['rule'], row['endpoint']))
    return {
        'route_count': len(routes),
        'routes': routes,
    }


def load_baseline(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_baseline(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True) + '\n', encoding='utf-8')


def _index_routes(payload):
    indexed = {}
    for row in payload.get('routes', []):
        indexed[(row['endpoint'], row['rule'])] = set(row.get('methods', []))
    return indexed


def diff_route_maps(baseline, current):
    baseline_index = _index_routes(baseline)
    current_index = _index_routes(current)

    removed = sorted(baseline_index.keys() - current_index.keys())
    added = sorted(current_index.keys() - baseline_index.keys())

    changed_methods = []
    for key in sorted(baseline_index.keys() & current_index.keys()):
        if baseline_index[key] != current_index[key]:
            changed_methods.append(
                {
                    'endpoint': key[0],
                    'rule': key[1],
                    'baseline_methods': sorted(baseline_index[key]),
                    'current_methods': sorted(current_index[key]),
                }
            )

    return {
        'removed': removed,
        'added': added,
        'changed_methods': changed_methods,
    }


def run_smoke_checks(flask_app):
    results = []
    with flask_app.test_client() as client:
        checks = [
            ('/healthz', {200, 503}),
            ('/login', {200}),
            ('/', {302}),
        ]
        for path, allowed in checks:
            rv = client.get(path)
            ok = rv.status_code in allowed
            results.append({'path': path, 'status_code': rv.status_code, 'ok': ok})

    failed = [row for row in results if not row['ok']]
    return {'results': results, 'failed': failed}


def cmd_snapshot(baseline_path: Path):
    current = collect_route_map(app)
    write_baseline(baseline_path, current)
    print(f'Wrote baseline with {current["route_count"]} routes to {baseline_path}')
    return 0


def cmd_check(baseline_path: Path, run_smoke: bool):
    if not baseline_path.exists():
        print(f'Baseline file not found: {baseline_path}')
        print('Run: python verification/refactor_guard.py snapshot')
        return 2

    baseline = load_baseline(baseline_path)
    current = collect_route_map(app)
    diff = diff_route_maps(baseline, current)

    print(f'Baseline routes: {baseline.get("route_count", 0)} | Current routes: {current.get("route_count", 0)}')
    print(f'Added: {len(diff["added"])} | Removed: {len(diff["removed"])} | Method changes: {len(diff["changed_methods"])}')

    if diff['removed']:
        print('\nRemoved routes:')
        for endpoint, rule in diff['removed']:
            print(f'  - {rule} [{endpoint}]')

    if diff['changed_methods']:
        print('\nRoutes with method changes:')
        for row in diff['changed_methods']:
            print(
                '  - '
                f"{row['rule']} [{row['endpoint']}] "
                f"baseline={row['baseline_methods']} current={row['current_methods']}"
            )

    if diff['added']:
        print('\nAdded routes (allowed):')
        for endpoint, rule in diff['added'][:20]:
            print(f'  + {rule} [{endpoint}]')
        if len(diff['added']) > 20:
            print(f'  ... and {len(diff["added"]) - 20} more')

    if run_smoke:
        smoke = run_smoke_checks(app)
        print('\nSmoke checks:')
        for row in smoke['results']:
            marker = 'OK' if row['ok'] else 'FAIL'
            print(f"  - {row['path']}: {row['status_code']} ({marker})")
        if smoke['failed']:
            return 1

    if diff['removed'] or diff['changed_methods']:
        return 1

    print('\nRefactor guard check passed.')
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description='Route-level refactor guard for incremental app modularization.')
    parser.add_argument('command', choices=['snapshot', 'check'])
    parser.add_argument('--baseline', default=str(DEFAULT_BASELINE))
    parser.add_argument('--no-smoke', action='store_true', help='Skip HTTP smoke checks in check mode')
    return parser.parse_args()


def main():
    args = parse_args()
    baseline_path = Path(args.baseline)

    if args.command == 'snapshot':
        raise SystemExit(cmd_snapshot(baseline_path))

    raise SystemExit(cmd_check(baseline_path, run_smoke=not args.no_smoke))


if __name__ == '__main__':
    main()
