# 精简公开发布格式

`leaderboard-lite-v1` 用于把已经完成、已经导出的原始结果发布到云端和结果页面。每个任务保留真实评分、可读动作轨迹、原始公开说明、三视角视频、终态证据与成本。发布过程不运行模型或模拟器，不恢复实验，也不改变自动化状态。

这是独立的发布附属文件 `publication-manifest.json`，不是对旧 `manifest.json` 的升级或覆盖。原始本地归档、已经公开的完整清单与历史文件继续保留。只有新发布的精简文件不包含观测图片、`public_session` 或原始会话日志；视频中的原始观测画面仍保留。

## 文件和来源

精简清单使用 `publication_manifest_version: leaderboard-lite-v1`，沿用原始 `run_id`、`algorithm`、`protocol`、`scene`、`status`、`outcome` 和完整 `costs`，并保留 `attempt`、`timestamps`、`audit`。`environment` 保留原有公开字段并过滤私有基础设施信息，未知值仍为 `null`。不把历史环境补成当前环境。

`provenance.source_manifest_sha256` 是原始清单文件字节的 SHA256。`reused_original` 默认为 `false`，只对明确复用的旧条件结果设为 `true`，且必须提供 `reuse_reason`。普通历史结果的导出不算此类复用。复用也不修改原始算法、策略哈希、协议、运行标识或成本，不声称重新执行了目标条件。

允许的文件类型只有：`native_result`、`episode_complete`、`native_ack`、`trajectory`、`public_timeline`、`costs`、`source_lock`、`environment`、`native_video` 和 `public_demo`。除可选的环境附属 JSON 外，必须包含这些证据及至少三个不同视角的原始视频。环境本身始终记录在清单中。禁止图片文件、嵌入式图片、公开会话文件、私有会话标识、认证信息和原始推理。轨迹和公开说明必须来自原始导出，不补写理由。

每个列出的文件保留原始相对路径、SHA256、字节数和媒体类型。原始结果、`episode_complete`、最终 `action_complete` 及终态 ACK 的控制数必须一致，评分和成功标记必须一致，`unstable_envs` 必须为空。成本 JSON 必须与清单的完整尝试列表一致，失败或未知用量的尝试不能省略；缓存 token 是输入 token 的子集，不额外累加，未知用量保持 `null`。

## 本地接口

```python
from robodojo_collab.publication import export_publication, validate_publication, build_panel

result = export_publication(source_bundle, exact_destination_directory,
    provenance={"reused_original": False, "reuse_reason": None})
errors = validate_publication(result["manifest"], result["bundle"])
panel = build_panel(publication_manifests_or_paths, task_registry,
                    "astra-l3-cap20-seed0-scene0",
                    algorithm_id="astra_l3_persistent_cap20")
```

`export_publication` 只复制白名单中的原始文件。目标目录中的相同输出会校验后复用；内容冲突、额外文件、SHA 不符或隐私字段会使发布失败。返回值包含 `manifest`、`manifest_path`、`manifest_sha256`、`bundle`、`files`、`bytes` 和 `status`。不会改写源清单。

`validate_publication` 返回错误列表；空列表表示通过所请求的检查。没有提供本地目录或设置 `check_files=False` 时，只检查元数据，不能作为文件完整性或云端验证的证明。

`build_panel` 返回小型索引，不重复嵌入所有轨迹、成本明细或视频。索引中的 `summary`（兼容别名 `official54`）使用 0–100 的评分和成功率；`capabilities` 按五类能力返回分项。每条 `runs` 记录保留原始算法、协议、环境、复用来源、成本摘要以及指向网站根目录的 `data/publications/<panel_id>/runs/<run_id>.json`。

同一面板必须采用完整原始 54 任务目录、同一 seed/layout/round，每个已纳入任务恰好一条原始运行。同一目标条件的任务时长上限及历史导入描述可以不同；其他算法和执行协议字段必须一致。仅在显式给出目标 `algorithm_id` 且逐条提供复用说明时，才能纳入不同历史条件。缺任务的部分面板总分为 `null`，不能按零分补全；重复任务直接拒绝。

## 云端、网页和评分边界

### 原始 Devset10 的明确范围

已有完整的 Devset10 可使用单独的 `devset10` profile 发布。必须显式提供固定的 `devset10-v1` 名单，包含原十个任务、seed0/layout0/round0；缺例不能计算总体成绩，也不能替换任务。Score 与 SR 分别按每个任务 1/10 等权计算，能力分项仅作描述。网页标记为 Devset10，不使用 Full54 或官方完整榜单的标签。默认 `full54` 的名单、统计和旧清单保持原样。

本地调用为 `build_panel(..., profile="devset10", task_registry=<固定名单>)`。文件发布器需增加 `--profile devset10 --task-registry <固定名单文件>`；同样先核对原生结果、终态、最终动作 ACK、全部费用与逐文件 SHA，再做云端匿名下载校验。发布范围元数据放在独立索引和详情附属字段，不改写原始运行清单。

云端采用不可变 SHA 文件及独立存储位置记录。每个上传对象需读回并验证 SHA 后才能标记已验证。网页入口、下载链接和视频播放链接是不同能力，应分别记录。链接能打开或上传进度结束不能代替字节校验。

可以把一个面板的精简清单与 JSON 证据打成一个仅含元数据的包，再把视频作为独立 SHA 对象上传或复用已有对象，避免在包中重复上传视频。此时存储记录必须明确 `package.scope: panel`、包的 SHA、包内路径，以及每段独立视频的 SHA 和位置；下载包不应被描述为“包含视频的单任务完整包”。完整本地精简目录仍保留全部视频以供校验。包、索引与存储记录的构建不能删除原始文件或旧公开结果。

评分沿用官方五能力等权，Generalization 的 standard/random 各占一半。采用这个加权公式不表示完成官方全部评测：本试点是预算限制下单个 seed/layout 的 54 任务结果，不能称为跨 seed 鲁棒性证据，也不能称为已获官方验证的排行榜提交。官方流程还要求提交适配器 PR，并经过评测和代码审核；见 [RoboDojo 官方提交流程](https://robodojo-benchmark.com/doc/usage/robodojo-submission/)。

CPU 校验：`python -m unittest discover -s tests -p 'test_publication.py' -v`。测试不调用付费模型、GPU 或网络。

## 纯 VLA 的历史结果

纯 VLA 基线与“GPT＋VLA”分别登记。纯 VLA 使用明确的 `native_vla` 执行类型，保留原模型、可核验的 checkpoint／配置来源、原生动作表示与时序；Codex 客户端、语言模型付费请求和 token 不适用，不能生成虚假的零费用回执。没有计量的 GPU 时长或金额仍为未知。策略推理次数、RPC 次数与控制步分别记录，不能由控制步或预测块长度推算实际推理调用数。

导出仍需逐例核对原 `_result`、`episode_complete`、最终 `action_complete`、控制数、场景 SHA 和三路原视频。可读轨迹来自原始数值动作及执行反馈；没有模型自然语言说明时明确说明缺少该类说明，不补写理由。原始来源未保存的历史代码或权重 SHA 保持未知，当前文件的 SHA 不能证明历史运行采用该版本。纯 VLA 的模拟器兼容补跑及原结果复用也必须披露依据。

同样先完成本地证据与隐私验证，再上传并匿名读回校验。只有实际完整的 54 任务才能使用 Full54 面板；旧的标准 42 任务及不完整批次不自动纳入这个范围。

## 发布一个完整面板

把逐例精简目录放在同一父目录后，可以调用文件专用发布器：

```sh
python scripts/publish_panel.py <精简目录父路径> \
  --panel-id <稳定面板ID> --algorithm-id <目标算法ID> \
  --title '<展示标题>' --server https://cloud.tsinghua.edu.cn \
  --library <已有资料库ID> --site-origin https://zefanw.github.io \
  --state .local/publication-state/<面板ID>
```

凭据沿用 `docs/STORAGE.md` 的仓库外配置，不能放进命令参数或提交。发布器先验证完整54例和官方场景哈希；重用已验证的相同SHA对象，只上传新文件。它生成一份不含图片和视频的面板JSON证据包，逐个登记可读轨迹与视频位置，并更新网页的轻量目录、逐例详情和CSV。匿名下载SHA校验失败时不会登记完成。候选播放地址仍需独立浏览器验证，不能仅凭文件下载成功宣称浏览器兼容。

网页文件经CPU测试和公开信息扫描后提交到同一仓库；GitHub Pages成功部署、线上索引和可读轨迹可访问之后，才视为对外发布完成。发布器不自动提交Git，不启动或恢复任何实验。
