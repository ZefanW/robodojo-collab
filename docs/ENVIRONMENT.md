# Controller and simulator setup

The controller can run on macOS or Linux. The simulator needs its own supported NVIDIA RTX/Linux environment. SSH is optional: choose `transport.mode=local` when both run on one machine. Each contributor signs in to their own Codex account. Never send credentials to the simulator or publish `.private/`, `auth.json`, sessions, or raw Codex logs.

## Exact source and model contract

The implemented algorithm is `astra-l3-persistent-cap20`, Astra medium, Codex CLI **0.153.4**. The published model name is an alias; its server-side weights are not frozen. The original Apple ARM binary SHA is recorded in the registry for provenance, not as the expected SHA on Linux. Obtain the official 0.153.4 build for your platform, run `--version`, compute its SHA256, and explicitly record it in your private configuration. If that version or Astra entitlement is unavailable, report the limitation. Do not substitute a current client, model, provider, or API key.

[Official Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference) describes `codex login` and `codex login status`; [app-server documentation](https://learn.chatgpt.com/docs/app-server) describes its stdio transport. Use the pinned binary to log in yourself. Current documentation is not a promise that all current flags exist in the frozen client. This implementation retains the flags actually used by the recorded 0.153.4 baseline. The API model page does not prove your Codex account has Astra access; no paid entitlement probe is made by `doctor`.

Prepare Python 3.12 for the controller and install the repository requirements. The frozen RoboProbe code has its own requirements (`openai==3.8.0`, `pillow==12.3.0` at the recorded revision); install its declared dependencies in your controller environment after reviewing them. Controller modules do not import Isaac Sim.

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

Install the simulator using the frozen upstream instructions and the selected version's NVIDIA documentation. The recorded baseline used Sim5.1 and Sim6.0.0.1; the latter recorded Torch2.11.0. Do not install the latest IsaacLab blindly: it may not support Sim5.1. Recorded dependency revisions include IsaacLab `afca7b09d60d8beb9c1cb28b43066499940b969b` and cuRobo `d17b54ce32cba095c0b000c4c58777075d11de0e`; source patches and simulator-specific runtime differences must be retained. A clean upstream dependency install has **not** been validated on a new GPU for this release.

[NVIDIA's 5.1 requirements](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html) and compatibility checker are the starting point for driver, RTX renderer, OS and GPU support. They are separate from the weaker free-memory guard in this runner. `nvidia-smi` success or an A800's VRAM does not prove RTX camera support. A100/A800 must not be assumed to support Isaac's RTX renderer. Never replace system glibc or drivers as an automatic fix.

Assets come from the [RoboDojo-Benchmark/RoboDojo Hugging Face dataset](https://huggingface.co/datasets/RoboDojo-Benchmark/RoboDojo/tree/91f76c28d93dd20c5fa46ce6a5a1d96a4f384acd), pinned to `91f76c28d93dd20c5fa46ce6a5a1d96a4f384acd`. Its pinned README metadata declares Apache-2.0; no separate dataset LICENSE file was available at that revision. This is a metadata observation, not a blanket relicensing of every referenced asset. `registry/assets.lock.json` records the upstream file sizes and LFS SHA256 or Git-blob SHA1; `registry/scenes.json` separately pins actual layout SHA256. No assets or checkpoints are redistributed here. Inspect the planned download and upstream terms first:

```sh
python scripts/fetch_assets.py --destination vendor/RoboDojo
# After explicit license acceptance and checking the space report:
python scripts/fetch_assets.py --destination vendor/RoboDojo --download --accept-upstream-licenses
```

The helper fetches only Assets (no VLA checkpoints), resumes with the standard Hugging Face cache, refuses insufficient space, and verifies every saved file against the pinned digest. Completed matching files are reused. The planned total excludes checkpoints; provision enough extra space for cache/temp copies. Network availability and contributor licensing/access must still be checked locally.

## Read-only checks and source preparation

```sh
python -m robodojo_collab.doctor --config .private/contributor.json --output .private/controller-doctor.json
# On the simulator host, using its actual environment:
/path/to/simulator/python -m robodojo_collab.doctor --config .private/contributor.json --output .private/simulator-doctor.json
python scripts/prepare_native.py --robodojo vendor/RoboDojo --roboprobe vendor/RoboProbe --family Sim6 --output-lock .private/native-source-lock.json
```

`prepare_native` requires a contributor-owned clean pinned checkout, checks that the compatibility patch applies, adds preserved audit hooks and installs the frozen cap20 policy. It does not touch another project's checkout or start a GPU. Put the generated map into `simulator.native_source_sha256`. Preserve the resulting environment/dependency record, source hashes and native log as public sanitized provenance. The Sim5.1 and Sim6 main/eval files are distinct recorded sources; do not combine them.

`doctor` reports the actual process's cgroup version/hierarchy limits and installed package metadata; host `free` or CPU counts are not substituted. Native launch requires at least 12,000 MiB free on the selected GPU and 47 GiB actual cgroup startup headroom. These are conservative scheduler gates, not a guarantee that every task fits. On a Linux desktop without a finite cgroup, available memory comes from `/proc/meminfo`'s `MemAvailable`; with a cgroup, the smaller of that and the process's remaining cgroup allowance is used. Unknown memory remains blocked. Check disk needs for downloaded archives, extracted assets, cache and video before downloading. Configure project-local `LD_PRELOAD`, `LD_LIBRARY_PATH`, `VK_ICD_FILENAMES` only from diagnosis of that machine. Sim6's websocket interface requires `websockets>=14`; the recorded working environment used15.0.1.

## Simulator/task mapping

`registry/simulator-mapping.json` preserves all 54 actual baseline assignments (23 Sim6, 31 Sim5.1). Repetitions must use the task's assigned family. This table is a comparability requirement, not proof that every other family fails. Earlier Sim6 initialization failed for `fold_clothes`, `fold_clothes_random`, `deposit_coin`, `plug_in_charger`, `pour_by_language`, `pour_liquid_into_cup`, and `pour_liquid_into_cup_random`; those original cases later used Sim5.1. Native invalid initialization remains unscored. Do not convert it into zero or quietly select a different layout.

This release has CPU validation and preserved historical evidence, **not** an end-to-end fresh machine GPU validation. Source preparation cannot prove rendering or physics validity. Before contributing a score, verify all three real camera images, native action ACK, exact selected layout and source hashes, native `_result.json`/`episode_complete`, and zero unresolved initialization errors. A launched process or exited simulator alone is never a completed result.
