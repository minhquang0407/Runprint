# QR — Reproducible Research Execution Wrapper

**Product & Technical Specification — MVP v0.1**

> *“Run anything. Capture everything needed to reproduce it.”*

```bash
qr run -- python train.py --config configs/baseline.yaml
qr show QR-20260914-001
qr rerun QR-20260914-001
```

**Working name:** QR  
**Principles:** Local-first · Framework-agnostic · Open-source core  
**Date:** September 2026

# 1. Tóm tắt điều hành

> **Định nghĩa sản phẩm**
>
> QR là một reproducible execution wrapper: nó chạy bất kỳ experiment command nào, tự capture state cần thiết của run, ghi lại quá trình thực thi, và tạo một run record có thể inspect, compare và rerun về sau.

MVP không cố trở thành framework training, không thay PyTorch/JAX/Hugging Face, không tự thiết kế model, và chưa có cloud/GPU scheduler. QR đứng bên ngoài experiment code như một lớp execution + provenance mỏng, đủ nhỏ để một người có thể xây nhưng đủ nền tảng để phát triển thành research infrastructure.

Value proposition cốt lõi: một experiment đã chạy qua QR không được trở thành “run bí ẩn” mà vài tuần hoặc vài tháng sau researcher không còn biết chính xác code, config, environment, dataset version và artifacts nào đã tạo ra kết quả đó.

| **Mục tiêu**    | **V0.1 làm gì**                                                                               | **V0.1 chưa làm**                                        |
|-----------------|-----------------------------------------------------------------------------------------------|----------------------------------------------------------|
| Reproducibility | Capture code state, config, env, hardware, data reference, command, logs, metrics, artifacts. | Không đảm bảo bit-for-bit identical trên mọi GPU/driver. |
| Execution       | Wrap arbitrary process: Python, Bash, binary, simulation.                                     | Không thay training framework.                           |
| Local-first     | Lưu run record trong .qr/, không cần server.                                                  | Chưa có hosted dashboard/cloud sync.                     |
| Research UX     | qr init / run / list / show / rerun.                                                          | Chưa có collaboration, scheduler, agent.                 |

# 2. Vấn đề cần giải quyết

Trong research, đặc biệt ML/AI, một kết quả tốt thường được tạo ra trong môi trường thay đổi liên tục: code chưa commit, config sửa tay, package update, dataset thay đổi, seed khác, GPU khác, checkpoint nằm rải rác và logs bị mất. Kết quả là researcher có thể biết “run này đạt 87.4%” nhưng không còn biết run đó đến từ state nào.

```text
edit code
→ train
→ edit code
→ train
→ edit config
→ train
→ “Run nào đã tạo ra 87.4%?”
```

Pain này xuất hiện trước khi cần tới MLOps hay enterprise platform. Vì vậy wedge hợp lý nhất là giải quyết provenance/reproducibility của một run trước, thay vì build toàn bộ experiment platform ngay từ ngày đầu.

# 3. Product thesis và định vị

QR không phải “CLI để chạy Python”. Shell đã làm việc đó rất tốt. QR tạo thêm một reproducibility envelope quanh process.

```text
qr run <anything>
│
▼
code + config + environment + data reference
│
▼
EXECUTE
│
▼
logs + metrics + artifacts + exit state
│
▼
reproducible run record
```

> **One-liner positioning**
>
> QR makes every research experiment reproducible.
> Technical version: Run anything. Capture everything needed to reproduce it.

# 4. Nguyên tắc thiết kế

- Framework-agnostic: QR wrap process thay vì sở hữu training loop.

- Local-first: V0.1 chạy hoàn toàn local, không cần account, cloud hay database server.

- Explicit over magical: QR tự capture những gì có thể xác định chắc chắn; data/config đặc thù nên được researcher khai báo thay vì đoán.

- Provenance before orchestration: trước khi remote/cloud/GPU scheduler, phải làm run record đáng tin cậy.

- Reproducibility is a contract, not a slogan: phân biệt rõ captured, restorable và reproducible.

- Low adoption friction: một command phải đủ để nhận value ngay.

- Composable: CLI + tiny SDK; future cloud/agent layer dùng cùng run abstraction.

# 5. User journey cốt lõi

Happy path của V0.1 nên đơn giản đến mức researcher hiểu được trong vài phút:

```bash
$ qr init
Initialized QR project in .qr/
$ qr run -- python train.py --config configs/baseline.yaml
Run QR-20260914-001 started
Snapshot captured
... training output ...
Run completed: exit=0, duration=02:31:08
$ qr show QR-20260914-001
...
$ qr rerun QR-20260914-001
```

Nếu repository đang dirty, QR phải làm researcher nhận ra ngay rằng run vẫn được trace đúng bằng cách lưu git diff, thay vì ép họ commit trước khi chạy.

```text
⚠ Working tree contains uncommitted changes.
Snapshotting diff:
train.py
model.py
configs/base.yaml
```

# 6. Execution model

QR gồm hai pha lớn: snapshot và execute. Snapshot được capture ngay trước khi child process bắt đầu. Execution layer giữ nguyên stdout/stderr ra terminal đồng thời tee vào file log, theo dõi PID/exit code/signal/duration và finalise run record khi process kết thúc.

```text
qr run
│
┌─────────┴─────────┐
▼ ▼
PRE-RUN SNAPSHOT EXECUTE CHILD
git / env / hw command argv
config / data refs stdout / stderr
│ │
│ metrics / artifacts
└─────────┬─────────┘
▼
FINALIZE RUN
status / duration / checksums
```

| **Phase** | **Capture/Action**                                       | **Failure policy**                                              |
|-----------|----------------------------------------------------------|-----------------------------------------------------------------|
| Preflight | Locate project, validate .qr, allocate run_id.           | Abort cleanly trước khi child process nếu project invalid.      |
| Snapshot  | Git, runtime, environment, hardware, declared inputs.    | Không chặn run vì metadata optional thiếu; đánh dấu incomplete. |
| Execute   | Spawn child process; stream + persist stdout/stderr.     | Propagate exit code; record signals/crash.                      |
| Collect   | Receive qr.log / qr.artifact events; detect output refs. | SDK failure không được âm thầm corrupt record.                  |
| Finalize  | End timestamp, duration, status, checksums, manifest.    | Atomic write/rename để tránh manifest nửa vời.                  |

# 7. Snapshot / Run Manifest

Snapshot không phải image toàn máy. Nó là một manifest có đủ provenance để giải thích run và, khi điều kiện cho phép, tái tạo execution context. Dữ liệu lớn và artifacts lớn được tham chiếu bằng URI/version/fingerprint thay vì copy mặc định.

```json
{
"schema_version": "0.1",
"run_id": "QR-20260914-001",
"command": ["python", "train.py", "--config", "configs/baseline.yaml"],
"cwd": "/workspace/my-research",
"timestamps": {
"started_at": "2026-09-14T09:12:04+07:00",
"finished_at": "2026-09-14T11:43:12+07:00"
},
"git": {
"commit": "92ac13...",
"branch": "experiment/vit",
"dirty": true,
"diff_file": "git.diff"
},
"runtime": {
"os": "Linux",
"python": "3.12.2",
"packages_lock": "environment/pip-freeze.txt"
},
"hardware": {
"cpu": "...",
"gpu": ["NVIDIA RTX 4090"],
"gpu_driver": "...",
"cuda": "..."
},
"inputs": {
"configs": ["configs/baseline.yaml"],
"datasets": [{
"name": "medvqa",
"uri": "/data/medvqa_v3",
"version": "v3",
"fingerprint": "sha256:..."
}]
},
"status": "completed",
"exit_code": 0,
"metrics_file": "metrics.jsonl",
"artifacts_file": "artifacts.json"
}
```

# 8. Capture policy: tự động vs khai báo

| **Loại**   | **QR có thể tự capture**                                                                          | **Cần researcher/SDK khai báo**                                 |
|------------|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| Git/source | repo root, commit, branch, dirty state, diff, remote URL (optional).                              | Các source ngoài repo hoặc generated code đặc thù.              |
| Runtime    | OS, kernel, Python executable/version, env vars allowlist, pip/uv/conda snapshot khi detect được. | Container image/private runtime metadata nếu không detect được. |
| Hardware   | CPU, RAM, GPU model/count, driver/CUDA khi tool hệ thống có sẵn.                                  | Remote accelerator abstractions đặc thù.                        |
| Config     | Command argv và file được truyền qua cờ explicit nếu parser hỗ trợ.                               | Config semantics; nên có qr input/config API.                   |
| Dataset    | Không nên đoán arbitrary filesystem là dataset.                                                   | URI, version, fingerprint strategy, metadata.                   |
| Metrics    | Có thể capture terminal text nhưng không parse metric đáng tin cậy.                               | qr.log(...) là source of truth.                                 |
| Artifacts  | Không tự upload/copy file lớn trong V0.1.                                                         | qr.artifact(path) để register reference/checksum.               |

> **Nguyên tắc**
>
> Không biến QR thành hệ thống “magic parsing”. Một metadata field không chắc chắn nên là unknown/undeclared thay vì QR đoán sai.

# 9. Reproducibility contract

“Rerun” không đồng nghĩa với “kết quả số học chắc chắn giống tuyệt đối”. Reproducibility của ML còn phụ thuộc nondeterministic GPU kernels, random seed, driver, compiler, external service, network dependency và khả năng truy cập lại dataset/artifact. QR nên công khai ba cấp độ:

| **Level**    | **Ý nghĩa**                                                       | **V0.1**                                                             |
|--------------|-------------------------------------------------------------------|----------------------------------------------------------------------|
| TRACEABLE    | Biết chính xác run đã dùng command/source/env/input refs nào.     | Mục tiêu bắt buộc.                                                   |
| RESTORABLE   | Có đủ recipe/lock/reference để dựng lại execution context hợp lý. | Best effort; phụ thuộc môi trường tồn tại.                           |
| REPRODUCIBLE | Rerun tạo output trong tolerance đã định nghĩa.                   | Không thể đảm bảo chung; researcher/project tự định nghĩa tolerance. |

Do đó \`qr rerun\` nên hiển thị preflight report: source có checkout được không, dirty diff có apply được không, environment có restore được không, dataset fingerprint còn match không, required artifacts còn tồn tại không.

```text
RERUN PREFLIGHT — QR-20260914-001
✓ git commit available
✓ dirty patch applicable
✓ Python environment lock available
✓ dataset fingerprint matches
! GPU differs: RTX 4090 → H100
→ reproducibility risk: hardware changed
```

# 10. CLI specification — V0.1

| **Command**           | **Mục đích**                             | **Output chính**                               |
|-----------------------|------------------------------------------|------------------------------------------------|
| qr init               | Khởi tạo QR project trong repo hiện tại. | .qr/project.json, ignore rules, project id.    |
| qr run -- \<command\> | Snapshot + execute + record.             | run_id, logs, manifest, status.                |
| qr list               | Liệt kê runs.                            | run id, status, duration, command, start time. |
| qr show \<run_id\>    | Inspect run.                             | source/env/input/result/artifact summary.      |
| qr rerun \<run_id\>   | Reconstruct/best-effort rerun.           | preflight + new run linked to parent.          |

Khuyến nghị dùng \`--\` để phân tách QR options khỏi child command. Ví dụ:

```bash
qr run --tag baseline -- python train.py --config configs/base.yaml
qr rerun QR-001 --allow-hardware-change
```

Một rerun nên tạo run mới, không overwrite run cũ:

```text
QR-001 original
└── rerun → QR-014
parent_run_id = QR-001
```

# 11. Tiny Python SDK

CLI phải mang lại value ngay cả khi researcher không sửa code. SDK chỉ thêm semantic events mà CLI không thể suy ra đáng tin cậy.

```python
import qr
for epoch in range(epochs):
train()
qr.log({
"epoch": epoch,
"loss": float(loss),
"val_accuracy": float(acc),
})
qr.artifact("checkpoints/best.pt", kind="model")
qr.input_dataset(
name="medvqa",
uri="/data/medvqa_v3",
version="v3",
)
```

| **API**                | **Semantics**                                        | **V0.1 storage**         |
|------------------------|------------------------------------------------------|--------------------------|
| qr.log(dict)           | Append structured metric/event.                      | metrics.jsonl            |
| qr.artifact(path, ...) | Register output artifact + metadata/checksum policy. | artifacts.json           |
| qr.input_dataset(...)  | Declare dataset reference/version/fingerprint.       | manifest.inputs.datasets |
| qr.note(text)          | Optional human annotation.                           | events/notes stream      |

# 12. Local storage model

```text
my-research/
├── train.py
├── configs/
├── .git/
└── .qr/
├── project.json
├── index.sqlite # optional; rebuildable index
└── runs/
├── QR-20260914-001/
│ ├── manifest.json
│ ├── git.diff
│ ├── stdout.log
│ ├── stderr.log
│ ├── metrics.jsonl
│ ├── artifacts.json
│ └── environment/
│ ├── pip-freeze.txt
│ └── system.json
└── QR-20260914-002/
```

Manifest + logs là source of truth. SQLite chỉ nên là index/cache để \`qr list\` nhanh; nếu DB hỏng, có thể rebuild từ run directories. Điều này giữ thiết kế local-first, portable và dễ debug.

# 13. Run state machine và crash recovery

```text
CREATED → SNAPSHOTTING → RUNNING → FINALIZING → COMPLETED
├────────→ FAILED
└────────→ INTERRUPTED
```

QR phải xử lý Ctrl+C, process crash và máy restart theo cách không làm mất provenance. Trước khi child process chạy, một manifest tối thiểu phải tồn tại. Khi finalize, nên dùng write-to-temp + atomic rename. Run bị mất process nhưng chưa finalize được đánh dấu \`orphaned/interrupted\` khi \`qr list\` hoặc \`qr doctor\` quét lại.

# 14. Killer feature: dirty Git snapshot

Trong workflow research thực tế, ép user commit trước mỗi run sẽ tăng friction và thường bị bỏ qua. QR nên snapshot diff chưa commit và untracked file metadata theo policy rõ ràng. Khi rerun, QR checkout commit gốc vào isolated worktree/temp workspace rồi apply patch.

> **Moment of value**
>
> Researcher không còn phải hỏi: “Model 87.4% này được chạy từ version code nào?”. QR có thể trả lời commit + patch + command + config + environment của đúng run đó.

Lưu ý: không nên mặc định copy toàn bộ untracked data lớn. Có thể capture danh sách, size, mtime và checksum cho file nhỏ/declared source; dữ liệu lớn nên khai báo là input dataset/artifact reference.

# 15. Scope V0.1

| **Must-have**    | **Chi tiết**                                                              |
|------------------|---------------------------------------------------------------------------|
| Project init     | Detect repo/root; tạo .qr/project.json.                                   |
| Run wrapper      | Arbitrary child command, signal forwarding, exit-code propagation.        |
| Pre-run snapshot | Git commit/branch/diff; cwd; argv; timestamps; basic OS/runtime/hardware. |
| Logs             | Tee stdout/stderr ra terminal + files.                                    |
| Manifest         | Versioned schema; atomic finalization.                                    |
| Local run index  | qr list/show hoạt động nhanh và không phụ thuộc server.                   |
| Rerun            | Preflight; isolated restore/best effort; parent-child lineage.            |
| Tiny SDK         | log + artifact + input dataset declaration.                               |
| Tests            | Unit + integration cho git dirty, success/fail, Ctrl+C, rerun.            |

# 16. Explicit non-goals V0.1

- Không tự sinh training code hoặc model architecture.

- Không parse/điều khiển mọi framework (PyTorch/JAX/TF/Lightning/HF).

- Không hosted dashboard, cloud account hoặc team workspace.

- Không GPU scheduler/orchestrator.

- Không copy/upload dataset lớn mặc định.

- Không object store cho checkpoint 20–100 GB.

- Không agent/AI scientist loop.

- Không enterprise SSO/RBAC/audit/compliance.

- Không hứa bit-exact determinism.

> **Kỷ luật sản phẩm**
>
> Nếu một feature không trực tiếp giúp “capture run state”, “inspect run” hoặc “rerun đáng tin hơn”, nó gần như chắc chắn phải chờ sau V0.1.

# 17. Product discovery sau V0.1

QR là “cửa sổ” vào workflow, không phải công cụ tự động biết toàn bộ workflow trước/sau. Việc mở rộng sản phẩm phải dựa trên observe + ask + instrument + integrate, không dựa trên suy đoán.

| Pain₁ → Tool → Usage → Observe Pain₂ → Feature₂ → Usage → ... |
|---------------------------------------------------------------|

| **Observed behavior**                               | **Pain suy ra**            | **Candidate feature**                      |
|-----------------------------------------------------|----------------------------|--------------------------------------------|
| Sau qr run, user luôn scp checkpoint về laptop.     | Artifact movement/storage. | qr artifact push / managed artifact store. |
| User luôn ssh → git pull → conda activate → qr run. | Remote execution friction. | qr run --on lab-gpu.                       |
| User screenshot metric gửi Discord/Slack.           | Collaboration/share.       | qr share / team workspace.                 |
| Nhiều user hỏi GPU nào đang trống.                  | Scheduling contention.     | GPU orchestration.                         |
| User lặp action sau lỗi OOM.                        | Manual recovery loop.      | Policy-driven retry / agent action.        |

# 18. Open-source và mô hình kiếm tiền

Open-source core là distribution wedge: researcher cá nhân có thể \`pip install\` và nhận value ngay. Business không cần charge cho local execution; charge ở hạ tầng/collaboration/control mà team và enterprise không muốn tự vận hành.

```text
OPEN-SOURCE CORE
CLI · local runs · local tracking · SDK · basic rerun
│
▼
HOSTED / PAID
team collaboration · cloud execution · GPU orchestration
artifact storage · agent execution
│
▼
ENTERPRISE
RBAC · audit · security · SSO · private registry
VPC / on-prem · compliance · support
```

| **Layer**   | **Ai trả tiền**                  | **Giá trị bán**                                                   |
|-------------|----------------------------------|-------------------------------------------------------------------|
| Open-source | Individual researcher            | Adoption, trust, community; free.                                 |
| Cloud/Lab   | Lab, startup, research team      | Convenience: sync, share, storage, compute, scheduling.           |
| Enterprise  | Biotech, hospital, large R&D org | Control/trust: security, permissions, audit, deployment, support. |

# 19. Các paid layer tương lai

| **Capability**         | **Ý nghĩa**                                                                              |
|------------------------|------------------------------------------------------------------------------------------|
| Team collaboration     | Shared project/run history, comments, compare/fork, dashboards, team ownership.          |
| Cloud execution        | \`qr run --cloud\`; provision compute, execute, stream logs, bill by usage.              |
| GPU orchestration      | Queue/schedule jobs theo GPU type/count/priority/budget; failure recovery.               |
| Large artifact storage | Managed object storage, dedup, versioning, retention cho checkpoints/embeddings/results. |
| Enterprise deployment  | Customer VPC/on-prem/private cloud; data không rời boundary.                             |
| Permissions            | RBAC/ABAC: view/run/edit/download/delete theo role/project/resource.                     |
| Audit                  | Immutable-ish event history: who did what, when, from where.                             |
| Security               | SSO/SAML/MFA, secret vault, encryption, network policy, key management.                  |
| Private registry       | Internal registry cho models/datasets/prompts/agents/eval suites.                        |
| Agent execution        | Budgeted/policy-guarded API để agent tạo/chạy/đánh giá experiment.                       |

# 20. Roadmap đề xuất

| **Phase**                  | **Product**                                                | **Success signal**                                            |
|----------------------------|------------------------------------------------------------|---------------------------------------------------------------|
| V0.1 — Local provenance    | run/show/list/rerun + tiny SDK.                            | 5–10 researchers dùng thật; có run họ quay lại inspect/rerun. |
| V0.2 — Compare & artifacts | run diff/compare, artifact references, better env restore. | User dùng QR thay notes/screenshot để nhớ experiments.        |
| V0.3 — Remote execution    | SSH/lab GPU target, lightweight remote runner.             | User bỏ manual ssh/pull/activate workflow.                    |
| V0.4 — Collaboration       | Hosted sync, team projects, share/compare.                 | Một researcher kéo cả lab vào.                                |
| V0.5 — Orchestration       | Queue, GPU scheduling, budget, storage.                    | Lab chạy phần đáng kể experiments qua QR.                     |
| V1 — Agent substrate       | Agent API + policy + approval + automated evaluation loop. | Agents thực hiện bounded research loops qua QR.               |

# 21. Từ run tracker tới autonomous research infrastructure

Đường dài của QR không phải thêm “AI chat” vào dashboard. Giá trị chiến lược xuất hiện khi cùng một run abstraction được dùng bởi cả humans và agents, trong khi QR sở hữu execution, provenance, policy và outcome feedback.

```text
Research question
↓
Hypothesis / experiment plan
↓
Research Agent
↓
QR execution substrate
↓
Run → Metrics → Artifacts → Evaluation
↓
Policy / budget / approval
↓
Next hypothesis
└──────────────────────↺
```

Ở giai đoạn đó, QR có thể tạo structured event stream dạng state → action → result → human/agent correction. Nhưng đây là hệ quả của adoption và integration depth; không phải lý do để overbuild MVP.

# 22. Privacy, security và data ownership

Ngay từ local-first MVP, QR nên thiết kế để researcher hiểu chính xác dữ liệu nào được capture. Không nên thu thập source code, dataset contents, secret hay proprietary artifact ra khỏi máy nếu user chưa bật cloud/sync và chưa consent rõ ràng.

- Default local; telemetry sản phẩm (nếu có) phải opt-in hoặc tối thiểu/anonymous theo policy minh bạch.

- Không serialize toàn bộ environment variables; secret-like keys phải redact theo pattern/allowlist.

- Dataset fingerprint không đồng nghĩa upload dataset.

- Artifact registration không đồng nghĩa upload artifact.

- Git diff có thể chứa secret; cần secret-scan warning và ignore policy.

- Mọi schema phải versioned để future migration/audit rõ ràng.

# 23. Failure modes cần thiết kế ngay

| **Failure**                | **Rủi ro**                    | **Expected behavior**                                      |
|----------------------------|-------------------------------|------------------------------------------------------------|
| Child command fails        | Run mất context.              | Record FAILED + exit code + logs; không xóa snapshot.      |
| Ctrl+C                     | Manifest incomplete.          | Forward signal; finalize INTERRUPTED best-effort.          |
| Disk full                  | Logs/manifest corrupt.        | Fail loudly; reserve/atomic manifest; surface exact error. |
| Git patch cannot reapply   | Rerun sai source.             | Preflight stops; không silently continue.                  |
| Dataset changed            | Result không comparable.      | Fingerprint mismatch warning/deny based on policy.         |
| Package restore impossible | False confidence.             | Mark RESTORE_INCOMPLETE; show missing dependencies.        |
| Secrets in diff/env        | Leak proprietary credentials. | Redact/scan; never cloud-sync silently.                    |

# 24. Acceptance criteria cho V0.1

- \`qr run -- \<command\>\` cho process exit 0 tạo run directory hoàn chỉnh và trả đúng exit code.

- Process exit != 0 vẫn tạo run record FAILED với stdout/stderr và snapshot đầy đủ.

- Git clean và dirty đều được capture; dirty diff có thể inspect lại.

- \`qr list\` hiển thị run history mà không cần network.

- \`qr show\` giải thích source/env/command/status của một run rõ ràng.

- \`qr rerun\` không overwrite original và tạo lineage parent_run_id.

- Rerun preflight phát hiện ít nhất: missing commit/patch, dataset mismatch (khi declared), hardware change.

- \`qr.log\` ghi metrics structured mà không parse stdout.

- \`qr.artifact\` register path và metadata mà không copy/upload file lớn mặc định.

- Ctrl+C không làm mất run record.

- Không capture secret env vars theo mặc định.

- Test suite chạy trên Linux; Windows/macOS có thể là follow-up nếu chưa đủ nguồn lực.

# 25. Backlog kỹ thuật ưu tiên

| **Priority** | **Task**                             | **Why now**                                 |
|--------------|--------------------------------------|---------------------------------------------|
| P0           | Project discovery + \`qr init\`      | Foundation cho mọi command.                 |
| P0           | Run ID + manifest schema v0.1        | Ổn định data model sớm.                     |
| P0           | Subprocess wrapper + signal handling | Core execution semantics.                   |
| P0           | Git snapshot + dirty diff            | Killer provenance feature.                  |
| P0           | stdout/stderr tee                    | Usability + debugging.                      |
| P0           | Finalization + crash-safe writes     | Data integrity.                             |
| P1           | Runtime/hardware detector            | Reproducibility context.                    |
| P1           | \`qr list\` / \`qr show\`            | Immediate inspect UX.                       |
| P1           | \`qr rerun\` + isolated worktree     | Core value proposition.                     |
| P1           | Tiny SDK events                      | Structured metric/artifact/input semantics. |
| P2           | SQLite rebuildable index             | Performance when run count grows.           |
| P2           | \`qr doctor\`                        | Detect orphaned/incomplete/corrupt runs.    |
| P2           | \`qr diff\` / compare                | Natural next feature.                       |

# 26. Naming và repository suggestion

CLI \`qr\` rất gọn, nhưng brand/repository có thể dùng tên dễ search hơn. Một cấu trúc hợp lý là giữ QR làm command/protocol identity trong khi repo/product dùng working name riêng.

```text
Product / Repo: Runprint (working candidate)
Python package: runprint
CLI: qr
Run ID: QR-20260914-A7F2
Tagline: Run anything. Reproduce everything.
```

Nếu chưa muốn chốt brand, repo giai đoạn prototype hoàn toàn có thể là \`qr\` hoặc \`qr-run\`, nhưng package/public release nên kiểm tra namespace, searchability và trademark trước khi công bố rộng.

# 27. North-star metric và validation

Không đo thành công MVP bằng số feature. Đo bằng việc researcher thật sự quay lại dùng record cũ để hiểu hoặc tái chạy experiment.

| **Metric**                       | **Ý nghĩa**                                   |
|----------------------------------|-----------------------------------------------|
| Weekly active researchers        | Tool có đi vào workflow thật không.           |
| Runs/researcher/week             | Độ sâu adoption.                              |
| % runs with dirty state captured | Pain provenance có xuất hiện thật không.      |
| Show-after-days                  | Có run được inspect lại sau 7/30 ngày không.  |
| Rerun rate                       | Reproducibility có value hay chỉ là logging.  |
| Declared dataset/artifact rate   | SDK semantics có đủ hữu ích.                  |
| Retention of first 5–10 users    | Quan trọng hơn sign-up count ở giai đoạn đầu. |

> **MVP validation**
>
> Mục tiêu ban đầu không phải 1.000 labs. Mục tiêu là 5–10 researchers nói rằng bỏ QR đi thì họ lại quay về trạng thái không biết run nào đã tạo ra kết quả nào.

# 28. Tóm tắt quyết định kiến trúc

- QR là wrapper, không phải trainer.

- Process command là abstraction trung tâm.

- Run record là primitive trung tâm.

- Manifest/logs là source of truth; DB chỉ là cache/index.

- Dataset/artifact lớn được reference, không copy mặc định.

- Metrics structured đi qua tiny SDK, không phụ thuộc stdout parsing.

- Dirty Git diff là first-class provenance.

- Rerun tạo lineage mới; không mutate history.

- Local-first/open-source core trước; cloud/enterprise sau khi có usage signal.

- Agent execution là destination dài hạn, không phải MVP feature.

> **Final product principle**
>
> V0.1 phải làm `qr run` và `qr rerun` đủ đáng tin để một researcher tin rằng experiment của họ sẽ không bao giờ trở thành một “mystery run” nữa.

# Phụ lục A — Example \`qr show\`

```text
Run QR-20260914-001
Status COMPLETED
Started 2026-09-14 09:12:04 +07
Duration 02:31:08
Command python train.py --config configs/baseline.yaml
SOURCE
Commit 92ac13...
Branch experiment/vit
Dirty diff yes (3 files)
RUNTIME
Python 3.12.2
Packages environment/pip-freeze.txt
CUDA 13.x
GPU NVIDIA RTX 4090 ×1
INPUTS
Config configs/baseline.yaml
Dataset medvqa:v3
Fingerprint sha256:a719...
RESULTS
accuracy 0.873
f1 0.821
ARTIFACTS
checkpoint.pt registered 20.3 GB
metrics.json registered 12 KB
REPRODUCIBILITY
Traceable YES
Restorable LIKELY
Risk GPU/kernel nondeterminism
```

# Phụ lục B — Câu hỏi cần kiểm chứng với 5–10 researcher đầu tiên

1.  Lần gần nhất bạn không reproduce được experiment cũ là khi nào? Bạn thiếu thông tin gì?

2.  Bạn hiện lưu config, seed, package version, dataset version và checkpoint ở đâu?

3.  Bạn có thường chạy khi Git chưa commit không? Khi đó bạn nhớ code state bằng cách nào?

4.  Sau 1–3 tháng, thứ gì khiến một run trở thành “mystery run”?

5.  Bạn có cần rerun y hệt hay chỉ cần biết rõ provenance để compare?

6.  Bạn có dùng W&B/MLflow/DVC/Slurm hiện tại không? QR phải coexist với chúng như thế nào?

7.  Phần nào của snapshot bạn sợ bị capture vì privacy/secret/IP?

8.  Sau khi một run kết thúc, bạn thường làm gì ngay tiếp theo?

9.  Bạn thường chuyển checkpoint/artifact đi đâu và bằng cách nào?

10. Điều gì khiến bạn chịu thêm `qr run --` vào command hiện tại mỗi ngày?

# Phụ lục C — Repository skeleton đề xuất

```text
qr/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/qr/
│ ├── cli.py
│ ├── project.py
│ ├── run.py
│ ├── manifest.py
│ ├── subprocess_runner.py
│ ├── snapshot/
│ │ ├── git.py
│ │ ├── runtime.py
│ │ └── hardware.py
│ ├── storage/
│ │ ├── local.py
│ │ └── index.py
│ ├── rerun.py
│ └── sdk.py
├── tests/
│ ├── unit/
│ └── integration/
└── examples/
├── pytorch/
├── bash/
└── simulation/
```
