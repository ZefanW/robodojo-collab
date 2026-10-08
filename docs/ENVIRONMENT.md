# Controller and simulator setup

For concrete historical failures and their limits, see [Chinese errata E01–E10](ERRATA_zh-CN.md#environment): RTX support, simulator differences, WebSocket interfaces, C++ libraries, executable PATH, client compatibility and passive quota evidence. The recorded fixes are diagnosis examples, not a universal installation script.

The controller can run on macOS or Linux. The simulator needs its own supported NVIDIA RTX/Linux environment. SSH is optional: choose `transport.mode=local` when both run on one machine. Each contributor signs in to their own Codex account. Never send Codex credentials to a separate simulator host or publish `.private/`, `auth.json`, sessions, or raw Codex logs.

Run commands from the collaboration repository root unless a command explicitly changes directory. JSON paths are **not shell expressions**: `$HOME` is not expanded, relative paths resolve against the process's current working directory, and not every field expands `~`. Use absolute paths in real configurations. The examples below show preparation commands; running this document is not permission to start paid inference.

## Choose one or two machines first

| Component | One Linux RTX machine | Controller plus SSH simulator |
|---|---|---|
| Collaboration repository | One checkout | Same release/commit checked out on both hosts |
| Controller Python, pinned Codex, own login | On that machine | On controller only |
| RoboProbe | Available to both Python environments | Separate pinned checkout on each host |
| RoboDojo, assets, Isaac, cuRobo, ffmpeg | On that machine | On simulator only |
| Claim token and Git/shared-ledger access | Local | Available privately on both; claim token is not a Codex credential |
| Immutable task package | One file | Copy the **same bytes** to both hosts |
| Config | `.private/contributor.json` can also serve native commands | `.private/contributor.json` locally; `.private/simulator.json` remotely |

For SSH, `transport.repository` is the **remote collaboration checkout**, `transport.python` is a remote Python capable of running its standard-library mailbox helper, and `transport.root` must be the exact absolute directory configured as the remote `simulator.output_root`. It is the parent directory of run IDs, not a particular run directory. `controller.roboprobe` always refers to the controller's local checkout. `simulator.robodojo`, `simulator.roboprobe`, `simulator.python`, and `simulator.output_root` are resolved on the host running `native-start`.

For local mode set `transport.mode="local"` and `transport.root=simulator.output_root`; SSH-only `host`, `repository`, and `python` fields are unused. This still needs Linux/NVIDIA for the simulator: local mode does not make Isaac run on a Mac.

Both hosts must retain their own original configuration and directories for resume. Use the same claim remote/branch, contributor, original token, public machine pseudonym, and immutable package; changing the native output root changes the execution binding. Never copy the whole `.private/` directory to set up SSH. Copy only the task package, a separately prepared simulator config, and the claim token over your own trusted connection. The simulator's unused controller/auth/budget placeholders do not require a Codex login.

On each host, create `.private` with owner-only permissions. The package installation itself needs no model account:

```sh
mkdir -p .private
chmod 700 .private
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For an already prepared environment, activate it; do not recreate it or overwrite an active run. Use the simulator's supported Python environment for Isaac dependencies, which may differ from the controller's 3.12 environment.

## Exact source and model contract

The implemented algorithm is `astra-l3-persistent-cap20`, Astra medium, Codex CLI **0.153.4**. The published model name is an alias; its server-side weights are not frozen. The original Apple ARM binary SHA is recorded in the registry for provenance, not as the expected SHA on Linux. Obtain the official 0.153.4 build for your platform, run `--version`, compute its SHA256, and explicitly record it in your private configuration. If that version or Astra entitlement is unavailable, report the limitation. Do not substitute a current client, model, provider, or API key.

[Official Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference) describes `codex login` and `codex login status`; [app-server documentation](https://learn.chatgpt.com/docs/app-server) describes its stdio transport. Use the pinned binary to log in yourself. Current documentation is not a promise that all current flags exist in the frozen client. This implementation retains the flags actually used by the recorded 0.153.4 baseline. The API model page does not prove your Codex account has Astra access; no paid entitlement probe is made by `doctor`.

The [official 0.153.4 release](https://github.com/openai/codex/releases/tag/rust-v0.153.4) and its [asset list](https://github.com/openai/codex/releases/expanded_assets/rust-v0.153.4) were checked on 2026-10-08. Download the complete `codex-package-...tar.gz` for the **controller** platform; retain its bundled files. Do not select a symbols archive, standalone app-server, or `latest` build.

| Controller platform | Release asset |
|---|---|
| macOS Apple Silicon | `codex-package-aarch64-apple-darwin.tar.gz` |
| macOS Intel | `codex-package-x86_64-apple-darwin.tar.gz` |
| Linux x86-64 | `codex-package-x86_64-unknown-linux-musl.tar.gz` |
| Linux ARM64 | `codex-package-aarch64-unknown-linux-musl.tar.gz` |

Download to a version-specific private installation directory. Verify the **archive** against the release's `codex-package_SHA256SUMS` before extraction. Inspect the extracted package for its actual `codex` executable and set the following to that absolute path. The archive digest is different from the executable digest required by the runner:

```sh
export ROBOCOLLAB_CODEX='/absolute/path/to/0.153.4/package/bin/codex'
"$ROBOCOLLAB_CODEX" --version
python - "$ROBOCOLLAB_CODEX" <<'PY'
import hashlib, pathlib, sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
```

Success is exactly `codex-cli 0.153.4`; put the path and printed executable SHA into `controller.codex` and `controller.codex_sha256`. A platform package being downloadable does not prove its app-server behavior on that platform. Run the localhost wire check in [RUNNING.md](RUNNING.md#offline-validation-commands) before live use. Do not overwrite the user's everyday Codex installation.

### Own-account login with the file store

The runner requires `controller.auth_home/auth.json` with a ChatGPT `tokens.account_id`. A desktop/keyring-only login is insufficient. The [official authentication documentation](https://learn.chatgpt.com/docs/auth#credential-storage) describes credential storage, and the [frozen 0.153.4 schema](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/core/config.schema.json) includes `cli_auth_credentials_store="file"`. Use a dedicated private home on the controller; the per-command setting below does not change your normal Codex home:

```sh
export ROBOCOLLAB_AUTH_HOME="$HOME/.config/robodojo-collab/codex-auth"
mkdir -p "$ROBOCOLLAB_AUTH_HOME"
chmod 700 "$ROBOCOLLAB_AUTH_HOME"
env CODEX_HOME="$ROBOCOLLAB_AUTH_HOME" "$ROBOCOLLAB_CODEX" \
  -c 'cli_auth_credentials_store="file"' login
env CODEX_HOME="$ROBOCOLLAB_AUTH_HOME" "$ROBOCOLLAB_CODEX" \
  -c 'cli_auth_credentials_store="file"' login status
```

Complete the browser flow yourself using your own account. On a headless **controller**, the frozen client's `login --device-auth` is available if your organization permits it. Do not use `--with-api-key`, another person's auth cache, or a model call to test entitlement. Store the expanded absolute auth-home path in the private config. Verify the required identity without printing any credential or account ID:

```sh
python - "$ROBOCOLLAB_AUTH_HOME" <<'PY'
import hashlib, json, pathlib, sys
p = pathlib.Path(sys.argv[1]) / 'auth.json'
d = json.loads(p.read_text())
account = (d.get('tokens') or {}).get('account_id')
if not account:
    raise SystemExit('ChatGPT file-store account identity missing; stop before inference')
print('account_identity_sha256=' + hashlib.sha256(account.encode()).hexdigest())
PY
```

Put that hash into `budget.account_identity_sha256`. Login does **not** create a quota snapshot; complete [QUOTA.md](QUOTA.md) before native startup. Missing or unbound passive evidence is a real unsupported first-run boundary in this release, not a reason to invent remaining allowance.

The frozen RoboProbe code has its own requirements (`openai==3.8.0`, `pillow==12.3.0` at the recorded revision); install its declared dependencies in the controller environment after reviewing them. There is no repository `requirements.txt`; `pip install -e .` installs the collaboration package. Controller modules do not import Isaac Sim. Prepare a separate RoboProbe copy and its dependencies in the simulator environment too:

```sh
git clone https://github.com/RoboProbe/RoboProbe.git vendor/RoboProbe
git -C vendor/RoboProbe checkout 9ffacc54f372beef6479d61711bf4945e31ae4ce
python -m pip install -e vendor/RoboProbe
```

`registry/source-lock.json` also locks the actual policy and wire-conversion files. A dirty or changed policy fails preflight. The runtime's original persistent bridge, context storage, action cap, and native observations remain separate from the newly written portable orchestration.

## Simulator sources and licenses

Download sources and assets yourself; this repository does not redistribute simulation assets, checkpoints, NVIDIA packages, or complete third-party environments.

```sh
git clone --recurse-submodules https://github.com/RoboDojo-Benchmark/RoboDojo.git vendor/RoboDojo
git -C vendor/RoboDojo checkout 08b7ee46034c3d0c8a389b2b7bfc138f4d55ee4d
git -C vendor/RoboDojo submodule update --init --recursive
```

The frozen RoboDojo `LICENSE` file contains [MIT terms](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/08b7ee46034c3d0c8a389b2b7bfc138f4d55ee4d/LICENSE), while its fetched README references non-commercial research terms. Both observations are recorded rather than treating the README as a blanket license for separate assets. This collaboration is for research; inspect the pinned license and applicable upstream terms before use or redistribution. RoboProbe is [Apache-2.0](https://github.com/RoboProbe/RoboProbe/blob/9ffacc54f372beef6479d61711bf4945e31ae4ce/LICENSE). Copies of applicable source notices are in `licenses/`. The adapted Codex transport carries the original GPT-as-Policy MIT attribution. NVIDIA software/assets and checkpoint repositories have their own terms; users must accept them directly before setting `license_accepted=true`.

On the **simulator host**, install the simulator using the [pinned upstream instructions](https://github.com/RoboDojo-Benchmark/RoboDojo/tree/08b7ee46034c3d0c8a389b2b7bfc138f4d55ee4d) and the selected version's NVIDIA documentation. The recorded baseline used Sim5.1 and Sim6.0.0.1; the latter recorded Torch2.11.0. Do not install the latest IsaacLab blindly: it may not support Sim5.1. Recorded dependency revisions include IsaacLab `afca7b09d60d8beb9c1cb28b43066499940b969b` and cuRobo `d17b54ce32cba095c0b000c4c58777075d11de0e`; source patches and simulator-specific runtime differences must be retained. A clean upstream dependency install has **not** been validated on a new GPU for this release. There is no verified universal one-command environment installer in this repository. Do not guess missing CUDA, compiler, IsaacLab, or cuRobo compatibility steps; record the blocker and the exact local versions.

[NVIDIA's 5.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html) and compatibility checker are the starting point for driver, RTX renderer, OS and GPU support. They are separate from the weaker free-memory guard in this runner. `nvidia-smi` success or an A800's VRAM does not prove RTX camera support. A100/A800 must not be assumed to support Isaac's RTX renderer. Never replace system glibc or drivers as an automatic fix.

Assets come from the [RoboDojo-Benchmark/RoboDojo Hugging Face dataset](https://huggingface.co/datasets/RoboDojo-Benchmark/RoboDojo/tree/91f76c28d93dd20c5fa46ce6a5a1d96a4f384acd), pinned to `91f76c28d93dd20c5fa46ce6a5a1d96a4f384acd`. Its pinned README metadata declares Apache-2.0; no separate dataset LICENSE file was available at that revision. This is a metadata observation, not a blanket relicensing of every referenced asset. `registry/assets.lock.json` records the upstream file sizes and LFS SHA256 or Git-blob SHA1; `registry/scenes.json` separately pins actual layout SHA256. No assets or checkpoints are redistributed here. Inspect the planned download and upstream terms first:

```sh
python -m pip install huggingface_hub
python scripts/fetch_assets.py --destination vendor/RoboDojo
# After explicit license acceptance and checking the space report:
python scripts/fetch_assets.py --destination vendor/RoboDojo --download --accept-upstream-licenses
```

`huggingface_hub` is an optional download dependency; it is not installed by the standard-library collaboration package or pinned RoboProbe requirements. The helper fetches only Assets (no VLA checkpoints), resumes with the standard Hugging Face cache, refuses insufficient space, and verifies every saved file against the pinned digest. The locked Assets set has 15,365 files totaling 41,269,513,111 bytes; a completely empty destination needs approximately 87.9 GB free under this helper's cache/temp guard. Completed matching files are reused. Network availability and contributor licensing/access must still be checked locally. If the helper reports an existing mismatched file, preserve and reconcile it; do not delete a live asset tree.

## Read-only checks and source preparation

```sh
python -m robodojo_collab.doctor --config .private/contributor.json --output .private/controller-doctor.json
# On the simulator host, using its actual environment:
/path/to/simulator/python -m robodojo_collab.doctor --config .private/simulator.json --output .private/simulator-doctor.json
python scripts/prepare_native.py --robodojo vendor/RoboDojo --roboprobe vendor/RoboProbe --family Sim6 --output-lock .private/native-source-lock.json
```

Use `--family Sim5.1` instead for a task mapped to Sim5.1. `prepare_native` requires a contributor-owned clean pinned checkout, checks that the compatibility patch applies, adds preserved audit hooks and installs the frozen cap20 policy. It does not touch another project's checkout or start a GPU. It is a one-time preparation, **not an idempotent repair**: it refuses an existing policy directory or a dirty tree. Preserve an existing prepared tree rather than repeatedly running it or resetting it.

Copy the generated JSON **object**, not its filename, into `simulator.native_source_sha256` in the simulator configuration:

```sh
python - <<'PY'
import json
from pathlib import Path
p = Path('.private/simulator.json')
c = json.loads(p.read_text())
c['simulator']['native_source_sha256'] = json.loads(Path('.private/native-source-lock.json').read_text())
p.write_text(json.dumps(c, indent=2) + '\n')
PY
```

For one-host mode update the config used for native startup. Preserve the resulting environment/dependency record and logs privately; publish only sanitized provenance through the exporter. The Sim5.1 and Sim6 main/eval files are distinct recorded sources; do not combine them. `doctor` is a report, not a pass/fail certifier: it may exit successfully while reporting missing dependencies or a wrong client. Controller success requires `codex.locked=true`; a simulator-only host can have no Codex installed. Inspect the simulator's actual `dependencies.isaacsim`, GPU/driver, available memory, and disk values. The runner additionally checks the selected scene/source hashes at startup; `runner check` alone checks only the package contract and controller source files.

For SSH mode, verify the existing host key and noninteractive access before running any scene:

```sh
ssh -o BatchMode=yes -o ForwardAgent=no -o StrictHostKeyChecking=yes YOUR_EXISTING_SSH_ALIAS \
  '/absolute/remote/python3 --version'
rsync --version
ssh -o BatchMode=yes -o ForwardAgent=no -o StrictHostKeyChecking=yes YOUR_EXISTING_SSH_ALIAS \
  'rsync --version'
```

Both sides of artifact collection need rsync 3 with `--protect-args`; the older rsync shipped with some macOS versions is insufficient. The collector invokes `rsync` from PATH, so select the installed version in your controller's PATH. SSH does not activate conda or your interactive shell; configure an absolute `transport.python` and absolute simulator interpreter path. The runner will not disable host-key verification or forward your SSH agent. The simulator itself also needs `ffmpeg` in the launch environment's PATH; `doctor.tools` reports its presence but does not install it.

`doctor` reports the actual process's cgroup version/hierarchy limits and installed package metadata; host `free` or CPU counts are not substituted. Native launch requires at least 12,000 MiB free on the selected GPU and 47 GiB actual cgroup startup headroom. These are conservative scheduler gates, not a guarantee that every task fits. On a Linux desktop without a finite cgroup, available memory comes from `/proc/meminfo`'s `MemAvailable`; with a cgroup, the smaller of that and the process's remaining cgroup allowance is used. Unknown memory remains blocked. Check disk needs for downloaded archives, extracted assets, cache and video before downloading. Configure project-local `LD_PRELOAD`, `LD_LIBRARY_PATH`, `VK_ICD_FILENAMES` only from diagnosis of that machine. Sim6's websocket interface requires `websockets>=14`; the recorded working environment used15.0.1.

## Simulator/task mapping

`registry/simulator-mapping.json` preserves all 54 actual baseline assignments (23 Sim6, 31 Sim5.1). Repetitions must use the task's assigned family. This table is a comparability requirement, not proof that every other family fails. Earlier Sim6 initialization failed for `fold_clothes`, `fold_clothes_random`, `deposit_coin`, `plug_in_charger`, `pour_by_language`, `pour_liquid_into_cup`, and `pour_liquid_into_cup_random`; those original cases later used Sim5.1. Native invalid initialization remains unscored. Do not convert it into zero or quietly select a different layout.

This release has CPU validation and preserved historical evidence, **not** an end-to-end fresh machine GPU validation. Source preparation cannot prove rendering or physics validity. Before contributing a score, verify all three real camera images, native action ACK, exact selected layout and source hashes, native `_result.json`/`episode_complete`, and zero unresolved initialization errors. A launched process or exited simulator alone is never a completed result.
