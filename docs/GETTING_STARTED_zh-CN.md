# 第一次下载：让 GPT‑6 / Codex 帮你跑一个 RoboDojo 场景

本页按实际执行顺序组织。所有命令默认在 **robodojo-collab 仓库根目录**运行；有两台机器时，每个代码块都会说明在哪台运行。先完成离线流程，再配置真实实验。下载仓库或打开网页不会自动调用模型。

## 先分清两个 Codex

| 用途 | 应如何配置 |
|---|---|
| 帮你读文档、准备环境的 Codex 助手 | 在 Codex 中打开本仓库，使用你账号可用的 GPT‑6 模型。把下方提示词发给它。 |
| 真正给机器人出动作的实验控制器 | 当前可执行入口固定为 `gpt-6-astra`、`medium`、独立安装的 Codex CLI **0.153.4**，由 runner 启动。 |

不用为了这个实验降级日常使用的 Codex 桌面应用或覆盖全局 CLI。把实验用的固定版本放到独立目录，在私有配置中填写它的绝对路径。桌面助手选了哪个模型，不会改变实验模型。模型可用性仍取决于账号与客户端，不能由模型列表推断。[官方模型说明](https://learn.chatgpt.com/docs/models)

当前 runner 只实现 `astra-l3-persistent-cap20`。网页中的 coor、full Codex、Sol61 和历史 persistent 结果是历史导入；**看到四种结果，不代表有四个可切换的启动参数**。新模型或新客户端应注册为另一个算法版本，不能只改原任务包里的模型名。

## 可以直接发给 Codex 的提示词

```text
请作为这个仓库的安装和运行助手，先读 AGENTS.md、README.md、
docs/GETTING_STARTED_zh-CN.md，再按需读 ENVIRONMENT、QUOTA、CLAIMS、RUNNING。
我的目标是用自己的账号和机器完成一个可审计的 RoboDojo 场景。

先只做环境发现、离线样例和配置准备；不要立即启动 GPU 或付费模型调用。
请自行检查可读取的 OS、Python、GPU、磁盘、已有 SSH 别名和安装目录，
不要让我填写你能可靠检测出来的信息。只向我询问无法推断的目标机器、
账号本人登录、额度保留值、上游许可接受和任务分配。

请区分日常 Codex 助手与实验固定的 GPT-6 Astra medium / CLI 0.153.4。
配置放 .private/，令牌放仓库外；不要输出或上传凭据。
根据本地/SSH 模式写清每条命令在哪台机器、用哪个 Python、读哪个配置。
首先运行离线 sample→validate→import→重复 import，检查命令之间的输出衔接。
再准备精确版本、场景包、模拟器源文件锁和权威 work-claims 认领。

对每一步告诉我“已通过的证据 / 具体缺什么 / 下一条操作”。
首次被动额度证据若无法可靠获取，或者通知缺少可核验的账号身份，
请明确报告这一兼容性缺口；不要填假时间或假额度，不要用付费探针绕过。
我确认自己的额度和执行范围、本人完成必要登录后，再启动一个已分配场景。
第一轮使用 --once 检查原生相机、动作 ACK 与保存的回复，然后使用原 run_id 恢复。
不要重置场景、重复付费回复、改换模型/账号，或为了修环境改掉固定协议。
最后按文档导出公开副本、校验、CLI 上传、登记 manifest 和存储记录并准备 PR。
```

如果使用的是只能聊天、不能读取本地文件和执行命令的网页聊天界面，仅发仓库链接不会自动完成安装。需要在有本地文件和终端能力的 Codex 项目中继续；本人登录和许可步骤仍由本人完成。

## 1. 准备条件与机器分工

| 位置 | 必需内容 | 不需要放在这里的内容 |
|---|---|---|
| 控制器：macOS 或 Linux | 本仓库、Python 3.10+（运行控制器推荐 3.12）、固定 RoboProbe 源码及依赖、固定 Codex CLI、自己的登录和额度证据 | SSH 模式不需要在控制器安装 Isaac Sim 或下载全部模拟资产 |
| 模拟器：受支持的 Linux + NVIDIA RTX 环境 | 本仓库同一提交、任务指定的 Sim5.1 或 Sim6、RoboDojo/RoboProbe、资产、ffmpeg、空闲 GPU/内存/磁盘 | 控制器的 Codex 登录文件、云盘上传令牌 |
| 提交结果 | 自己的 GitHub 账号/仓库 fork；自己可写的清华云盘资料库，或已约定的维护者文件接收方式 | 维护者的账号和凭据 |

也可以全放在同一台 Linux RTX 机器，此时选择 `transport.mode=local`。macOS 只运行控制器，不能把本页当作 Mac 原生 Isaac Sim 安装指南。Windows 本地执行未验证；可让 Codex 操作已配置好的 Linux 主机。

当前原生启动门槛包括选定 GPU 至少 **12,000 MiB 可用显存**、进程实际可用内存至少 **47 GiB**，默认输出盘至少 20 GiB；这是启动检查，不是完整安装所需空间或所有场景的性能保证。固定资产下载约 **41.27 GB**（不含模型 checkpoint），下载器另外计算缓存与临时空间。先看空间报告再下载。GPU 还需通过对应 Isaac Sim 的渲染兼容性检查，不能只看显存。[环境说明](ENVIRONMENT.md)

## 2. 先把不花模型额度的最小流程跑通

先确认 `python3 --version` 至少为 3.10；否则使用本机已有的合适解释器替换下面的 `python3`。

```sh
git clone https://github.com/ZefanW/robodojo-collab.git
cd robodojo-collab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
mkdir -p .private
python -m robodojo_collab sample .private/example
python -m robodojo_collab validate .private/example
python -m robodojo_collab import .private/example --store .private/example-store
python -m robodojo_collab import .private/example --store .private/example-store
```

按顺序应看到 `created`、`valid: true`、`imported`、`already_present`。重复导入不应创建新结果或覆盖旧结果。这个样例明确是合成的失败记录，不会生成机器人视频或有效分数；不要提交进公开 `results/`。

查看已经导入的真实历史结果：

```sh
python -m http.server 8080 --directory web
```

打开 `http://localhost:8080`。服务器占用当前终端，Ctrl-C 关闭网页服务；后续命令另开终端并重新进入仓库、激活虚拟环境。也可直接看[已发布网站](https://zefanw.github.io/robodojo-collab/)。

## 3. 固定版本、本人登录、准备源代码

按照 [ENVIRONMENT.md](ENVIRONMENT.md) 安装独立的 Codex 0.153.4 完整平台包，用该二进制做本人登录并记录 SHA。`controller.auth_home` 必须对应这次登录产生的目录；该 runner 要求其中存在文件式 `auth.json`，只登录桌面端或只存钥匙串不一定满足条件。不要把 `auth.json` 发给维护者、聊天助手或模拟器。

控制器需要固定的 RoboProbe 依赖；模拟器需要自己的完整环境。**`pip install -e .` 只安装协作工具，不会顺便安装 Isaac Sim、RoboProbe、CUDA、资产或 Codex。** 两台机器上的安装和解释器要分别核实。

在模拟器上准备自己独占的固定源码副本，下载资产并执行一次 `prepare_native.py`；它会修改这份副本、生成 `native-source-lock.json`。不能对正在运行的实验树重复套补丁。具体上游提交、模拟器映射、安装入口及检查命令见 [ENVIRONMENT.md](ENVIRONMENT.md)。遇到缺少版本或依赖冲突，保留诊断，不要随手升级到最新版本来消除报错。

## 4. 写任务包和私有配置

先从 `registry/simulator-mapping.json` 选定任务对应的模拟器，查看 `registry/scenes.json` 中实际存在的 seed/layout。下面仅展示命令格式，`stack_bowls / seed0 / layout1` 不是给所有人的自动分配：

```sh
cp configs/contributor.example.json .private/contributor.json
python scripts/make_package.py --task stack_bowls --seed 0 --layout 1 \
  --run-id MYNAME-stack-s0-l1-a0 --contributor MYNAME \
  --output .private/task.json
```

替换 `MYNAME`，使用公开英文/数字/短横线标识。首次原始尝试默认 `attempt=0`；有意重复试验需 `--attempt`、`--repeats-run-id` 和 `--reason`，不能通过换 run_id 抢同一份工作。seed 是官方目录 0/1/2，layout 是该目录内对应任务布局文件的排序序号，二者不互换。任务包创建后不要改内容；换参数应先重新核对分配。

配置里所有 `EDIT_*` / `YOUR_*` 都要替换。JSON 不会展开 `$HOME`、`$变量`；**可执行程序、源码、输出和令牌路径均建议填写绝对路径**。

| 配置项 | 填什么 / 从哪里来 |
|---|---|
| `controller.codex` / `codex_sha256` | 这台控制器的固定版本二进制绝对路径及实际 SHA，不复制别人平台的 SHA |
| `controller.auth_home` | 控制器本人登录的目录，内含文件式 auth.json |
| `controller.roboprobe` | 控制器上固定 RoboProbe 的源码目录 |
| `controller.state_root` | 控制器保存原会话和付费回复的私有持久目录；恢复时不换位置 |
| `budget.reserve_percent` | 由账号本人决定的剩余额度保留百分比；`null` 会阻止启动。不是“已用百分比” |
| `budget.allow_existing_credits` / `credit_reserve` | 是否允许用已有 credits 及保留量。默认不允许；工具不会购买 credits |
| `budget.account_identity_sha256` / `snapshot_file` | 本账号身份绑定及真实、足够新的被动额度通知，按 [QUOTA.md](QUOTA.md) 准备 |
| `transport.mode` | 单机 `local`；双机 `ssh` |
| `transport.host` / `python` / `repository` | SSH 别名、远端 Python 3.10+ 绝对路径、远端本仓库绝对路径；不是本机路径 |
| `transport.root` | 模拟器那台机器的输出根目录；必须等于远端 `simulator.output_root`，不要再附加 run_id |
| `simulator.family` | 任务在 registry 中对应的 `Sim5.1` 或 `Sim6` |
| `simulator.python` / `robodojo` / `roboprobe` | 模拟器解释器及其两份源码的绝对路径 |
| `simulator.output_root` / `gpu` / `port` | 自己的输出根目录、空闲 GPU 编号和未占用端口 |
| `simulator.native_source_sha256` | 将 prepare_native 生成的 JSON 对象填在这里；不是锁文件路径字符串 |
| `simulator.environment` | 仅填写该机器诊断后确实需要的运行环境覆盖；不要复制别人的库路径 |
| `simulator.machine_id` | 无敏感信息的稳定机器别名；它参与执行位置绑定 |
| `claim.remote` / `branch` | 合并分配后使用权威仓库 `https://github.com/ZefanW/robodojo-collab.git`、`work-claims` |
| `claim.token_file` | 仓库外的私有绝对路径，例如用户配置目录下 `one-scene-claim`；不能用 `.private/claim-token` |
| `execution_authorized` / `simulator.license_accepted` | 各项准备完成并由本人确认执行范围、预算/许可后才设为 true |

**SSH 模式是两份配置、一份完全相同的任务包。** 控制器 `.private/contributor.json` 填控制器自己的 `controller.*` 和远端 `transport.*`；模拟器 `.private/simulator.json` 填其实际 `simulator.*`。不要把控制器配置整份当作远端可用配置，也不要复制整个 `.private/`。只传所需任务包、模拟器配置及独立认领 token；两机用同一 Git 提交和同一 package，认领 token 是同一个值、路径可以不同。单机模式可以统一用 `.private/contributor.json`，把下方原生命令的配置参数相应替换。详细命令与字段对照见 [RUNNING.md](RUNNING.md)。

## 5. 认领与额度：两个独立的开始条件

**工作分配**：按 [CLAIMS.md](CLAIMS.md) 操作。普通外部贡献者通常没有主仓库写权限：在 fork 的分支准备精确 work_id、run_id 和模拟器 `execution_instance_id`，提交到主仓库 **work-claims 分支**的 PR，等接受后再运行。fork 自己的认领成功不等于上游已分配。`configs/accepted-assignment.example.json` 只是说明模板，不是可替代共享认领的启动凭证。

**额度证据**：必须来自自己账号的实际被动通知，保留原始观察时间并与登录身份匹配。当前工具不会自动从零生成首次额度快照；部分客户端通知还可能缺少 runner 要求的账号身份。这是实际兼容性门槛，详见 [QUOTA.md](QUOTA.md)。不能照抄示例里的数字、更新旧时间戳、靠发一次付费请求获得额度，或仅凭界面显示“还有额度”就绕过检查。

两个条件都满足后，运行只读检查：

```sh
python -m robodojo_collab.doctor --config .private/contributor.json \
  --output .private/controller-doctor.json
python -m robodojo_collab.runner check \
  --config .private/contributor.json --package .private/task.json
```

`check` 应返回 `package_valid: true`、`sources_valid: true`、`paid_calls: 0`。它主要校验任务包和源码，**并不表示登录、额度、认领、SSH、GPU、渲染已经全部通过**；doctor 同样是诊断报告而非整套环境认证。模拟器也必须用自己的环境单独执行 doctor。

## 6. 先启动原生场景，再启动自己的控制器

准备完成后按 [RUNNING.md](RUNNING.md) 执行：

| 顺序 / 位置 | 命令 | 应检查什么 |
|---|---|---|
| 模拟器主机 | `python -m robodojo_collab.runner native-start --config .private/simulator.json --package .private/task.json` | 原生进程和私有日志已记录；`launched_not_yet_native_action` 只是已启动，不能当作动作或成绩 |
| 控制器，启动后 | `python -m robodojo_collab.runner status --config .private/contributor.json --package .private/task.json` | 等待原生端产生非空 pending 请求后再启动控制器；没有 pending 时先查初始化日志 |
| 控制器 | `python -m robodojo_collab.runner start --config .private/contributor.json --package .private/task.json --once` | 处理首个可用请求边界后返回；可能产生实际模型费用 |
| 控制器 | `python -m robodojo_collab.runner status --config .private/contributor.json --package .private/task.json` | 原进程身份、pending 请求、原生动作 ACK；完整判定步骤见运行说明 |
| 控制器，确认首轮证据后 | `python -m robodojo_collab.runner resume --config .private/contributor.json --package .private/task.json` | 沿同一场景、同一模型会话继续，直到原生结束或出现明确 hold |

`--once` 限制控制器处理的边界；若当时没有 pending，也会直接返回，退出本身不证明产生了回复或动作。它不是“一条物理控制指令”、也不是“一次服务器响应的硬费用上限”。cap20 指每次 `move_eef` 只执行原计划前最多 20 个控制步，超出的后缀丢弃；模型决策另有 100 次上限。

首轮人工/助手检查至少包括：三路原生相机都是真实有效观察、场景 SHA 对应任务包、已保存回复与原生动作 ACK 对应、执行前缀没有超过 20。拿不到这些证据就先报告具体缺口。不要把“进程存活”当作实验已经正确开始。

## 7. 中断时不要重新 start

原生端保留 GPU 场景；控制器端保留原会话和所有付费收据。断线后先查原进程和文件，再按同一 run_id 执行：

```sh
python -m robodojo_collab.runner reconcile --config .private/contributor.json --package .private/task.json
python -m robodojo_collab.runner resume --config .private/contributor.json --package .private/task.json
```

注意 `reconcile` 可能把已经付费但未送达的回复送给原场景并执行动作，它不是纯查看命令。只在已授权继续原任务时使用。不要删输出目录、换 run_id、重复 native-start、重新登录别人的账号或手动补造会话。

主动暂停的方法、pause.request 路径、租约续期和过期处理见 [RUNNING.md](RUNNING.md) 与 [CLAIMS.md](CLAIMS.md)。无法确认是否已执行的回复保持 hold；当前 portable runner 不自动追加付费重试。

## 8. 完成、上传、提交的文件不要混在一起

```sh
python -m robodojo_collab.runner collect --config .private/contributor.json \
  --package .private/task.json --destination .private/collected
python -m robodojo_collab.export_new --controller .private/controller/MY_RUN_ID \
  --native .private/collected/MY_RUN_ID --package .private/task.json \
  --destination staging/my-contribution --tar
python -m robodojo_collab validate staging/my-contribution/MY_RUN_ID
python -m robodojo_collab import staging/my-contribution/MY_RUN_ID --store .private/verified-results
```

`MY_RUN_ID` 必须换成任务包实际 run_id；若改了 `controller.state_root`，同步使用那个真实路径。导出会核对原生终止、动作、环境、图片及费用，失败就保留现场，不要把字段手改成 complete。

随后按 [STORAGE.md](STORAGE.md) 用 CLI 上传生成的 TAR、需要独立播放的 MP4 和时间线，保存下载回验收据。新 portable 导出的公开演示是 HTML；可以从完整包解压后查看，不能把 HTML 的链接填成 MP4 播放地址。

| 内容 | 放哪里 |
|---|---|
| 原始会话、认证、额度快照、认领 token、机器私有配置 | 自己的私有目录；不进入 PR/云盘公共包 |
| 经过导出器筛选的图片、视频、公开动作/反馈和审计文件 | 清华云盘；按 SHA 校验，保留本地原档 |
| 不可变 `manifest.json` | 仅这一个轻量文件复制到 `results/RUN_ID/manifest.json` |
| 可更新的公共文件位置与回验结果 | 合并到 `registry/storage.json`，按 **每个 artifact SHA** 建立记录 |
| 生成的网页索引 | `web/data/index.json`；使用 metadata-only 模式重建 |

不要 `import --store results`：import 会复制所有证据，公开 Git 仓库只收 manifest。也不能只把整个 TAR 的 SHA 填入 `artifacts`，它和包内每个文件的 SHA 不同。[上传文档](STORAGE.md) 提供正确的 bundle/成员链接合并例子；[导出文档](EXPORT.md) 给出仅登记 manifest 的命令。首次完整验证应检查文件字节，`--manifest-only` 只是后续构建网页用的元数据检查。

提交前运行公开文件检查、重建索引、检查 Git 待提交文件列表，再向主仓库 **main** 提交结果 PR。工作分配 PR 去 work-claims，结果 PR 去 main，二者用途不同。失败或低分也要保留，不能挑最好的一次替换旧记录。

## 9. 遇到问题时，先定位在哪一层

更完整的 **[勘误与实际踩坑记录](ERRATA_zh-CN.md)** 收录 30 条问题，包含历史错误、当时的修复、当前版本适用范围和验收标准。第一次配置环境前建议浏览一遍；遇到中断后按症状查阅，不要逐条照抄修复。尤其先看额度证据缺口、已付费回复未送达、认领过期和公开下载回验。

| 现象 | 下一步 |
|---|---|
| `No module named robodojo_collab` | 回仓库根目录，确认当前解释器/虚拟环境，再 `python -m pip install -e .` |
| 登录成功却找不到 auth.json | 查看控制器 auth_home 是否正确、是否用了文件式认证；不要把钥匙串内容打印出来 |
| `Fresh passive allowance unavailable` / identity unknown | 按 QUOTA 核对真实通知、原时间和账号；不要改时间戳骗过检查 |
| `Portable source changed` / source mismatch | 核对固定提交和准备的副本；不要改锁文件去适配意外修改 |
| `Structural absence` / layout mismatch | 回场景目录核对真实 seed/layout；不要改为随机布局 |
| shared claim expired / changed owner | 停止新调用，查权威认领分支，保留原场景，走续期/核对流程 |
| `SSH mailbox unavailable` | 先用自己的 SSH 别名做只读连接，核对远端 Python、仓库和 output_root；不重启模型 |
| 显存、内存、端口不足 | 选自己已获分配的可用资源；不结束其他人的进程 |
| `Native run directory exists` | 这是防重复保护；检查该 run 原场景，不能删目录后重新启动 |
| 有 `_result.json` 但 export 失败 | 核对 episode_complete、ACK、控制步数和初始化错误，不能只凭单个文件判完成 |
| 视频分享链接打不开或不能内嵌 | 保留下载/云盘预览；浏览器验证成功前不标记 playback_url |

排查时可提供去敏后的错误、软件版本、公开 run_id 和命令名；不要贴 auth.json、完整环境变量、私有会话或令牌。当前已有 CPU 与历史证据验证；全新 GPU 机器、账号权益及被动额度通知兼容性仍需在你的环境核对。详见 [VALIDATION.md](VALIDATION.md)。
