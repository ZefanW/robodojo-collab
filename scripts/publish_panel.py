#!/usr/bin/env python3
"""Publish a validated image-free panel, reusing verified SHA-addressed media.

Input is a directory of already sanitized leaderboard-lite-v1 bundles. This
command never imports a simulator, experiment runtime, or model client.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from robodojo_collab.publication import validate_publication, build_panel, validate_panel_registry
from robodojo_collab.schema import file_sha256, privacy_findings, validate_registered_scene
from robodojo_collab.storage import publish, write_json


def read(path):
    return json.loads(Path(path).read_text())


def metadata_tar(bundles, output):
    """Only manifest and explicit non-media members; never a directory dump."""
    output = Path(output)
    temporary = output.with_suffix('.partial')
    size = sum(p.stat().st_size for b, m in bundles for p in
               [b / 'publication-manifest.json'] +
               [b / a['path'] for a in m['artifacts'] if a['kind'] not in ('native_video', 'public_demo')])
    if shutil.disk_usage(output.parent).free < size * 2 + 64 * 1024**2:
        raise ValueError('Insufficient actual space for metadata package and temporary copy')
    with tarfile.open(temporary, 'w', format=tarfile.USTAR_FORMAT) as tar:
        for bundle, m in sorted(bundles, key=lambda x: x[1]['run_id']):
            names = ['publication-manifest.json'] + [a['path'] for a in m['artifacts']
                    if a['kind'] not in ('native_video', 'public_demo')]
            for name in sorted(names):
                p = bundle / name
                if p.is_symlink():
                    raise ValueError('Symlink in publication')
                content = p.read_bytes()
                info = tarfile.TarInfo(m['run_id'] + '/' + name)
                info.size = len(content)
                info.mode = 0o644
                info.mtime = 0
                tar.addfile(info, io.BytesIO(content))
    if output.exists():
        if file_sha256(output) != file_sha256(temporary):
            raise ValueError('Existing immutable metadata package differs; use a new panel revision')
        temporary.unlink()
    else:
        temporary.replace(output)
    if output.stat().st_size > 128 * 1024**2:
        raise ValueError('Metadata package exceeds uploader limit; split publication explicitly')
    return output


def upload(path, args, cache, receipts):
    sha = file_sha256(path)
    previous = cache.get(sha)
    receipt_path = receipts / (sha + '.json')
    if receipt_path.exists():
        previous = read(receipt_path)
    if (previous and previous.get('sha256') == sha and
            previous.get('bytes') == path.stat().st_size and
            previous.get('verification') == 'remote_sha256' and
            previous.get('public_download_verified') and previous.get('download_url')):
        return deepcopy(previous), True
    publish(SimpleNamespace(server=args.server, library=args.library, file=str(path),
                            receipt=str(receipt_path), site_origin=args.site_origin))
    result = read(receipt_path)
    if not result.get('public_download_verified'):
        raise ValueError('Anonymous SHA readback incomplete; no public result registered')
    cache[sha] = result
    return result, result.get('action') == 'reused'


def update_catalog(web):
    panels = []
    for p in sorted((Path(web) / 'data/publications').glob('*/index.json')):
        item = read(p)
        s = item['summary']
        if not s['complete']:
            continue
        entry = {'panel_id': item['panel_id'], 'title': item['title'],
            'algorithm_id': item['algorithm_id'], 'official_seed': item['official_seed'],
            'layout_ordinal': item['layout_ordinal'], 'valid': s['valid'], 'planned': s['planned'],
            'score': s['score'], 'success_rate': s['success_rate'],
            'href': 'publications.html?panel=' + item['panel_id'],
            'index_url': 'data/publications/' + item['panel_id'] + '/index.json'}
        if item.get('metric_profile') in ('devset10', 'standard42'):
            entry.update(metric_profile=item['metric_profile'], metric_label=item['metric_label'],
                         scope=item['scope'], roster=item['roster'])
        if item.get('execution_kind') == 'native_vla':
            entry['execution_kind'] = 'native_vla'
        panels.append(entry)
    write_json(Path(web) / 'data/publications/catalog.json', {'schema_version': '1.0',
        'generated_at': datetime.now(timezone.utc).isoformat(), 'panels': panels})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundles', type=Path)
    parser.add_argument('--panel-id', required=True)
    parser.add_argument('--algorithm-id', required=True)
    parser.add_argument('--title', required=True)
    parser.add_argument('--server', required=True)
    parser.add_argument('--library', required=True)
    parser.add_argument('--site-origin', required=True)
    parser.add_argument('--web', type=Path, default=ROOT / 'web')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--storage-cache', type=Path, default=ROOT / 'registry/storage.json')
    parser.add_argument('--profile', choices=('full54', 'devset10', 'standard42'), default='full54',
                        help='Explicit scoring roster; default remains the original Full54 metric')
    parser.add_argument('--task-registry', type=Path,
                        help='Required for Devset10/Standard42; exact pinned roster, never an arbitrary subset')
    args = parser.parse_args(argv)
    if args.profile in ('devset10', 'standard42') and args.task_registry is None:
        parser.error(f'--profile {args.profile} requires an explicit --task-registry')
    registry_path = args.task_registry or ROOT / 'registry/tasks.json'
    task_registry, _ = validate_panel_registry(read(registry_path), args.profile)
    if not args.panel_id or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.panel_id):
        raise ValueError('Unsafe panel identifier')
    args.state.mkdir(parents=True, exist_ok=True)
    receipts = args.state / 'receipts'
    receipts.mkdir(exist_ok=True)
    bundles = []
    scenes = read(ROOT / 'registry/scenes.json')
    for p in sorted(args.bundles.glob('*/publication-manifest.json')):
        m = read(p)
        errors = validate_publication(m, p.parent, check_files=True) + validate_registered_scene(m, scenes)
        if errors:
            raise ValueError(p.parent.name + ': ' + '; '.join(errors))
        bundles.append((p.parent, m))
    panel = build_panel([m for _, m in bundles], task_registry,
                        args.panel_id, title=args.title, algorithm_id=args.algorithm_id, profile=args.profile)
    if not panel['summary']['complete']:
        if args.profile == 'full54':
            raise ValueError('Pilot publication requires all original 54 valid native terminals')
        if args.profile == 'devset10':
            raise ValueError('Devset10 publication requires all ten original valid native terminals; no missing-task zero fill')
        raise ValueError('Standard42 publication requires all 42 original standard valid native terminals; no missing-task zero fill')
    archive = metadata_tar(bundles, args.state / (args.panel_id + '-evidence.tar'))
    cache = read(args.storage_cache).get('artifacts', {}) if args.storage_cache.exists() else {}
    br, reused = upload(archive, args, cache, receipts)
    package = {**br, 'scope': 'panel', 'format': 'tar', 'run_count': len(bundles),
               'contains_images': False, 'contains_videos': False}
    if args.profile in ('devset10', 'standard42'):
        package.update(metric_profile=args.profile, roster_id=panel['roster']['id'])
    output = args.web / 'data/publications' / args.panel_id
    (output / 'runs').mkdir(parents=True, exist_ok=True)
    objects = {br['sha256']: {'bytes': br['bytes'], 'reused': reused}}
    for bundle, original in bundles:
        m = deepcopy(original)
        for art in m['artifacts']:
            if art['kind'] in ('native_video', 'public_demo', 'public_timeline'):
                receipt, reused = upload(bundle / art['path'], args, cache, receipts)
                objects[art['sha256']] = {'bytes': art['bytes'], 'reused': reused}
                if art['kind'] == 'public_timeline':
                    mirror = args.web / 'data/timelines' / (art['sha256'] + '.json')
                    mirror.parent.mkdir(parents=True, exist_ok=True)
                    if mirror.exists() and file_sha256(mirror) != art['sha256']:
                        raise ValueError('Immutable timeline mirror collision')
                    if not mirror.exists():
                        shutil.copyfile(bundle / art['path'], mirror)
                    receipt.update(timeline_url='data/timelines/' + mirror.name,
                                   timeline_source_sha256=art['sha256'])
                art['storage'] = receipt
            else:
                art['storage'] = {'provider': 'tsinghua', 'download_url': br['download_url'],
                    'landing_url': br['landing_url'], 'verification': 'bundle_remote_sha256',
                    'bundle_sha256': br['sha256'], 'bundle_member': m['run_id'] + '/' + art['path'],
                    'member_sha256': art['sha256'], 'bundle_format': 'tar',
                    'verified_at': br['verified_at'], 'public_download_verified': True}
        m['package'] = package
        if args.profile in ('devset10', 'standard42'):
            m['publication_scope'] = {'metric_profile': args.profile, 'metric_label': panel['metric_label'],
                                      'roster': panel['roster'], 'official_leaderboard_submission': False}
        if privacy_findings(m):
            raise ValueError('Public detail privacy check failed')
        write_json(output / 'runs' / (m['run_id'] + '.json'), m)
        print(json.dumps({'prepared_run': m['run_id']}), flush=True)
    panel['package'] = package
    panel['upload_summary'] = {'unique_objects': len(objects),
        'referenced_bytes': sum(o['bytes'] for o in objects.values()),
        'uploaded_bytes': sum(o['bytes'] for o in objects.values() if not o['reused']),
        'reused_objects': sum(o['reused'] for o in objects.values()), 'original_image_count': 0}
    panel['generated_at'] = datetime.now(timezone.utc).isoformat()
    if privacy_findings(panel):
        raise ValueError('Panel privacy check failed')
    write_json(output / 'index.json', panel)
    update_catalog(args.web)
    with (output / 'scores.csv').open('w', newline='', encoding='utf-8-sig') as f:
        keys = ['run_id', 'task', 'capability', 'variant', 'status', 'score_percent', 'success',
                'control_steps', 'model_decisions', 'actual_responses', 'simulator', 'reused_original']
        writer = csv.DictWriter(f, keys, extrasaction='ignore'); writer.writeheader(); writer.writerows(panel['runs'])
    write_json(args.state / 'published.json', {'panel_id': args.panel_id,
               'summary': panel['summary'], 'upload_summary': panel['upload_summary'],
               'index_sha256': file_sha256(output / 'index.json'), 'time': panel['generated_at']})
    print(json.dumps({'complete': True, 'panel_id': args.panel_id, **panel['upload_summary']}))


if __name__ == '__main__':
    main()
