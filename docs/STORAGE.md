# Tsinghua Cloud storage from the command line

Code, small manifests and the dashboard live in GitHub. Videos, images, public audit files and bundles live in Tsinghua Cloud, an independently authenticated Seafile service. No contributor needs the maintainer's account.

This CLI requires access to your own Tsinghua Cloud account/library. A Codex or GitHub account does not provide university cloud access. If you lack access, stop before uploading and ask the maintainer for an explicitly approved artifact handoff; the current CLI does not implement anonymous upload links, and you must not borrow the maintainer's token or silently choose another storage service.

## One-time authentication

Seafile's official CLI supports API-token authentication for SSO installations; a university SSO password is not a CLI password. This repository uses the documented Seafile HTTP API from Python, so the upload command works on macOS and Linux without a background sync daemon.

Create or obtain an API token in your own cloud account's profile using the service's supported login flow. Then enter it **in your local terminal**, never in chat, Git, a command argument, an issue, or a result:

```sh
python -m robodojo_collab.storage login
python -m robodojo_collab.storage status --library YOUR_LIBRARY_UUID
```

The credential is saved in `~/.config/robodojo-collab/seafile-token` with mode 0600, outside this repository. You may instead set `ROBOCOLLAB_SEAFILE_TOKEN` in your private process environment or `ROBOCOLLAB_SEAFILE_TOKEN_FILE` to a protected external file. No authentication data is exported. The token's server-side scope is determined by your Seafile deployment; do not assume it is library-scoped. Prefer a library-scoped credential when supported. This adapter currently uses the account-token endpoints.

## Validate, upload and read back

Only upload a bundle that passes the exporter and public validator. Keep original session data private. Export creates allowlisted copies; it does not modify originals.

The [portable export procedure](EXPORT.md#new-portable-run-exports) writes a private summary containing the exact bundle and TAR paths. Run the following from the main code checkout. Replace the library UUID with a library you can write; a public share ID is not a library UUID.

```sh
export RDC_RUN_ID="$(python -c 'import json; print(json.load(open(".private/task.json"))["run_id"])')"
export RDC_EXPORT_SUMMARY=".private/export-${RDC_RUN_ID}.json"
export RDC_CLOUD_LIBRARY='YOUR_WRITABLE_LIBRARY_UUID'
export RDC_RECEIPTS=".private/receipts/$RDC_RUN_ID"
export RDC_BUNDLE="$(python -c 'import json,os; print(json.load(open(os.environ["RDC_EXPORT_SUMMARY"]))["bundle"])')"
export RDC_ARCHIVE="$(python -c 'import json,os; from pathlib import Path; d=json.load(open(os.environ["RDC_EXPORT_SUMMARY"])); print(Path(d["bundle"]).parent/d["archive"]["file"])')"
mkdir -p "$RDC_RECEIPTS"
python -m robodojo_collab validate "$RDC_BUNDLE"
python -m robodojo_collab.storage publish "$RDC_ARCHIVE" \
  --library "$RDC_CLOUD_LIBRARY" --receipt "$RDC_RECEIPTS/bundle.json"
```

Each remote object is named with its full SHA-256 followed by the original basename. Existing objects are downloaded and checked before reuse. Uploads use `replace=0`. A lost upload acknowledgement triggers a read-only reconciliation and never an automatic duplicate POST. Resume the same command to retry only after checking whether the exact object already exists. Concurrent publications of an identical object may still create a server-renamed duplicate; the command fails closed when this is observed. Use one publisher per library or disjoint contribution prefixes, and keep the receipt.

The command downloads the remote bytes and compares SHA-256; Seafile's internal file ID is **not** treated as SHA-256. It creates a read-only file share and tests downloading it without the API credential. It records a download URL only when those bytes match. Temporary server download/upload capabilities are never recorded in public manifests.

Publish the original native MP4s individually if you want dashboard video playback. This serial loop also includes historical MP4 demos, but deliberately excludes the portable HTML demo. It creates one receipt named by each artifact's own SHA and stops at the first failed upload. If interrupted, rerun only after reconciling the reported object; already-present content is checked and reused.

```sh
python - <<'PYMEDIA'
import json, os, subprocess, sys
from pathlib import Path
rdc_bundle = Path(os.environ['RDC_BUNDLE'])
rdc_manifest = json.loads((rdc_bundle / 'manifest.json').read_text())
for rdc_artifact in rdc_manifest['artifacts']:
    if not rdc_artifact['media_type'].startswith('video/'):
        continue
    subprocess.run([sys.executable, '-m', 'robodojo_collab.storage', 'publish',
                    str(rdc_bundle / rdc_artifact['path']), '--library', os.environ['RDC_CLOUD_LIBRARY'],
                    '--receipt', str(Path(os.environ['RDC_RECEIPTS']) / ('artifact-' + rdc_artifact['sha256'] + '.json'))],
                   check=True)
PYMEDIA
```

`playback_candidate` means HTTP bytes and MIME type passed, not that a browser played it. Open the candidate in a browser, verify metadata, actual playback and seeking, and record the date/browser outcome. Only after that check should the corresponding private receipt set `browser_playback_verified: true` and copy the tested candidate to `playback_url`. Leave it null otherwise. A share landing page is not a playable video URL; the dashboard ignores unverified candidates.

Portable runs export an **HTML** public demo, with relative links to the three original videos. Its reliable fallback is the complete TAR download, extraction with the original directory structure, then opening the local demo. Do not assign a standalone HTML share a video playback URL. An optional public action timeline can be individually uploaded as JSON; the storage CLI records `json_url` only when public byte and CORS checks pass. Without it, the dashboard retains the archive download fallback. Tiny same-origin timeline mirrors require a separate exact-SHA check before committing; no mirror is fabricated automatically.

## Large files and resumability

The minimal adapter limits individual objects to 128 MiB. Split a large, deterministic archive into 64 MiB content-addressed parts:

```sh
python -m robodojo_collab.storage pack staging/PUBLIC_RUN.tar --output staging/chunks --chunk-mib 64
```

Publish each part and `chunks.json`. A restart reuses verified parts; no incomplete object is marked committed. Reassemble in the explicit order in `chunks.json`, checking each part and the final whole-file SHA. Split archives support download and audit; publish MP4s separately if inline playback is needed. Do not overwrite an old result with a new archive.

## Index receipts separately

The returned TAR receipt describes the **archive SHA**. The index instead looks up each manifest artifact's **individual SHA**. Copying a TAR receipt under its archive SHA in `artifacts` does not register the files inside it.

Use `bundles[run_id]` for the complete archive receipt. For each contained file, add `artifacts[file_sha]` with the bundle URL, `bundle_sha256`, `bundle_member` relative path, and `verification: "bundle_remote_sha256"`. This means the uploaded archive was read back and verified; it does not pretend that each member has its own public URL. A verified individually published MP4 receipt can replace that same run's bundle fallback with `verification: "remote_sha256"`.

The following merge uses the `RDC_*` variables from the upload section. It validates the local bundle again, requires a publicly downloadable SHA-matched archive receipt, preserves other contributors' existing mappings, and only promotes this run's member fallback when an individually verified receipt exists. It prints no credentials or private paths. A location conflict or failed check stops before editing the registry; review it rather than discarding an existing record.

```sh
python - <<'PYMERGE'
import hashlib, json, os, tarfile
from pathlib import Path
from robodojo_collab.cli import atomic_json
from robodojo_collab.schema import file_sha256, load_manifest, privacy_findings

rdc_bundle = Path(os.environ['RDC_BUNDLE'])
rdc_archive = Path(os.environ['RDC_ARCHIVE'])
rdc_receipts = Path(os.environ['RDC_RECEIPTS'])
rdc_manifest = load_manifest(rdc_bundle)
rdc_bundle_receipt = json.loads((rdc_receipts / 'bundle.json').read_text())

def rdc_check_receipt(rdc_receipt, rdc_sha, rdc_size):
    rdc_probe = rdc_receipt.get('public_probe', {})
    if (rdc_receipt.get('provider') != 'tsinghua'
        or rdc_receipt.get('verification') != 'remote_sha256'
        or rdc_receipt.get('sha256') != rdc_sha or rdc_receipt.get('bytes') != rdc_size
        or rdc_receipt.get('public_download_verified') is not True
        or rdc_probe.get('ok') is not True or rdc_probe.get('sha256') != rdc_sha
        or not rdc_receipt.get('download_url') or not rdc_receipt.get('verified_at')):
        raise SystemExit('Receipt lacks a matching verified public download. Resolve the share before registration.')

rdc_archive_sha = file_sha256(rdc_archive)
rdc_check_receipt(rdc_bundle_receipt, rdc_archive_sha, rdc_archive.stat().st_size)
rdc_expected = {rdc_a['path']: rdc_a['sha256'] for rdc_a in rdc_manifest['artifacts']}
rdc_expected['manifest.json'] = file_sha256(rdc_bundle / 'manifest.json')
with tarfile.open(rdc_archive, 'r:') as rdc_tar:
    rdc_members = rdc_tar.getmembers()
    if (len(rdc_members) != len(rdc_expected)
        or {rdc_m.name for rdc_m in rdc_members} != set(rdc_expected)
        or any(not rdc_m.isfile() for rdc_m in rdc_members)):
        raise SystemExit('TAR contents differ from the validated public bundle; do not register member URLs.')
    for rdc_member in rdc_members:
        rdc_hash = hashlib.sha256()
        with rdc_tar.extractfile(rdc_member) as rdc_stream:
            for rdc_chunk in iter(lambda: rdc_stream.read(1024 * 1024), b''):
                rdc_hash.update(rdc_chunk)
        if rdc_hash.hexdigest() != rdc_expected[rdc_member.name]:
            raise SystemExit('TAR member SHA differs from the public manifest; preserve evidence for review.')
rdc_registry_path = Path('registry/storage.json')
rdc_registry = json.loads(rdc_registry_path.read_text()) if rdc_registry_path.exists() else {}
rdc_bundles = rdc_registry.setdefault('bundles', {})
rdc_locations = rdc_registry.setdefault('artifacts', {})
rdc_run = rdc_manifest['run_id']
if rdc_run in rdc_bundles and rdc_bundles[rdc_run].get('sha256') != rdc_archive_sha:
    raise SystemExit('A different archive is already registered for this run; preserve it and request review.')
rdc_bundles.setdefault(rdc_run, rdc_bundle_receipt)

for rdc_artifact in rdc_manifest['artifacts']:
    rdc_sha = rdc_artifact['sha256']
    rdc_location = {rdc_key: rdc_bundle_receipt.get(rdc_key) for rdc_key in
                    ('provider', 'remote_name', 'landing_url', 'download_url', 'verified_at', 'public_download_verified')}
    rdc_location.update(verification='bundle_remote_sha256', bundle_sha256=rdc_archive_sha,
                        bundle_member=rdc_artifact['path'], playback_url=None)
    rdc_individual = rdc_receipts / ('artifact-' + rdc_sha + '.json')
    if rdc_individual.is_file():
        rdc_location = json.loads(rdc_individual.read_text())
        rdc_check_receipt(rdc_location, rdc_sha, rdc_artifact['bytes'])
        if rdc_location.get('browser_playback_verified') is not True:
            rdc_location['playback_url'] = None
        elif rdc_location.get('playback_url') != rdc_location.get('playback_candidate'):
            raise SystemExit('Playback URL differs from the browser-tested candidate; review before promotion.')
    rdc_existing = rdc_locations.get(rdc_sha)
    if rdc_existing is None:
        rdc_locations[rdc_sha] = rdc_location
    elif (rdc_existing.get('verification') == 'bundle_remote_sha256'
          and rdc_existing.get('bundle_sha256') == rdc_archive_sha and rdc_individual.is_file()):
        rdc_locations[rdc_sha] = rdc_location

if privacy_findings(rdc_registry):
    raise SystemExit('Public receipt registry failed privacy scanning; do not commit it.')
atomic_json(rdc_registry_path, rdc_registry)
print('Public locations merged; prior run manifests and unrelated location records preserved.')
PYMERGE
```

This checks the consistency of recorded receipts; it does not replace the maintainer's independent download and SHA verification. For a new contribution, finish the [manifest-only Git copy and index rebuild](EXPORT.md#new-portable-run-exports), review the diff, and submit a PR to `main`. Never copy `.private`, the TAR, videos or account-token files into the repository. Existing expired links can be replaced through a separate reviewed location update; the immutable experiment manifest must stay unchanged.

References checked during implementation: [Seafile CLI and SSO tokens](https://help.seafile.com/syncing_client/linux-cli/), [upload-link API](https://seafile-api.readme.io/reference/get_api2-repos-repo-id-upload-link), [multipart upload](https://seafile-api.readme.io/reference/post_seafhttp-upload-api-upload-token-ret-json-1), [share-link API](https://seafile-api.readme.io/reference/post_api-v2-1-share-links), [Tsinghua Cloud clients](https://its.tsinghua.edu.cn/1wzcycejdh_content.jsp?wbnewsid=3935&wbtreeid=1775).
