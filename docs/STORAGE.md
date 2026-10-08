# Tsinghua Cloud storage from the command line

Code, small manifests and the dashboard live in GitHub. Videos, images, public audit files and bundles live in Tsinghua Cloud, an independently authenticated Seafile service. No contributor needs the maintainer's account.

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

```sh
python -m robodojo_collab validate staging/PUBLIC_RUN
python -m robodojo_collab.storage publish staging/PUBLIC_RUN.tar.gz \
  --library YOUR_LIBRARY_UUID --receipt staging/receipts/PUBLIC_RUN.json
```

Each remote object is named with its full SHA-256 followed by the original basename. Existing objects are downloaded and checked before reuse. Uploads use `replace=0`. A lost upload acknowledgement triggers a read-only reconciliation and never an automatic duplicate POST. Resume the same command to retry only after checking whether the exact object already exists. Concurrent publications of an identical object may still create a server-renamed duplicate; the command fails closed when this is observed. Use one publisher per library or disjoint contribution prefixes, and keep the receipt.

The command downloads the remote bytes and compares SHA-256; Seafile's internal file ID is **not** treated as SHA-256. It creates a read-only file share and tests downloading it without the API credential. It records a download URL only when those bytes match. Temporary server download/upload capabilities are never recorded in public manifests.

Native and public-demo MP4s can also be published individually. `playback_candidate` means HTTP bytes and MIME type passed; promote it to `playback_url` only after browser media playback succeeds. A share landing page is not a playable video URL. Login requirements, expired links, missing CORS or blocked codecs require a cloud-preview/download fallback. The dashboard never embeds an unverified candidate.

## Large files and resumability

The minimal adapter limits individual objects to 128 MiB. Split a large, deterministic archive into 64 MiB content-addressed parts:

```sh
python -m robodojo_collab.storage pack staging/PUBLIC_RUN.tar.gz --output staging/chunks --chunk-mib 64
```

Publish each part and `chunks.json`. A restart reuses verified parts; no incomplete object is marked committed. Reassemble in the explicit order in `chunks.json`, checking each part and the final whole-file SHA. Split archives support download and audit; publish MP4s separately if inline playback is needed. Do not overwrite an old result with a new archive.

## Index receipts separately

Use a public receipt overlay keyed by artifact SHA:

```json
{"artifacts":{"<SHA256>":{"provider":"tsinghua","landing_url":"https://…","download_url":null,"playback_url":null,"verification":"remote_sha256","verified_at":"2026-10-08T00:00:00Z"}}}
```

Apply this when building the index. This updates locations without changing the original immutable run manifest. Maintain download fallbacks and dates; link validity is a live property.

References checked during implementation: [Seafile CLI and SSO tokens](https://help.seafile.com/syncing_client/linux-cli/), [upload-link API](https://seafile-api.readme.io/reference/get_api2-repos-repo-id-upload-link), [multipart upload](https://seafile-api.readme.io/reference/post_seafhttp-upload-api-upload-token-ret-json-1), [share-link API](https://seafile-api.readme.io/reference/post_api-v2-1-share-links), [Tsinghua Cloud clients](https://its.tsinghua.edu.cn/1wzcycejdh_content.jsp?wbnewsid=3935&wbtreeid=1775).
