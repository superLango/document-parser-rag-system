# M4 里程碑详细执行计划：沙箱服务与执行引擎

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 计划周期：2026-12-31 ~ 2027-01-13  
> 主责角色：项目负责人（兼沙箱/平台/DevOps）  
> 协作角色：外部无（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0](M0-project-scaffold.md)、[M1](M1-core-domain-orchestration.md)、[M3](M3-recipe-registry.md)  
> 当前状态：计划中（未开工）

---

## 1. 里程碑目标

建立可隔离执行配方/模板代码的沙箱服务：

- 容器执行，默认无网络、只读根文件系统、非 root、资源受限。
- 按 `engine_digest + recipe_digest` 挂载版本，保证可复现。
- 产物 schema/哈希校验后离开沙箱。
- 支持超时、OOM、非零退出、非法产物的稳定错误分类。
- 开发 Compose 与生产 K8s 同一执行契约。

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| Sandbox API | `/internal/sandbox:execute` |
| 运行时 | containerd/Kata/gVisor 三选一；M4 K4.1 PoC + 评分后确定（Q3） |
| 运行时评估 | 安全性 30%、资源开销 25%、兼容性 25%、运维复杂度 20% |
| 评估报告 | 运行时评分矩阵 + 结论 + 回填决策记录 |
| 镜像 | 引擎运行时镜像 + 配方包挂载 |
| 挂载 | `/engine`、`/recipes`、`/templates`、`/input`、`/output` |
| 隔离 | 无网络、只读、非 root、cap drop、seccomp |
| 限制 | CPU/内存/PID/超时 |
| 产物 | result/records/evidence/diagnostics/metrics/manifest |
| 校验 | schema、sha256、路径穿越、符号链接 |
| 测试 | 隔离、确定性、超时、OOM、崩溃 |

### 2.2 不做

- 不做 OCR（M2）。
- 不做配方匹配（M3）。
- 不做 Agent（M5）。
- 不做反馈/晋升（M6）。
- 不做前端（M7）。
- 不实现多租户隔离（本期无租户）。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M0 完成 | 服务骨架、CI、Compose |
| M1 完成 | 编排可调用沙箱阶段 |
| M3 完成 | 配方包、digest、通道 |
| 容器运行时 | WSL/Linux 测试环境可用 |
| WSL K8s | M0 已固定发行版；用于 NetworkPolicy/资源限制验证 |
| 镜像仓库 | 可推送/拉取镜像 |
| 节点资源 | CPU/内存/临时存储 |
| 运行时 PoC | containerd/Kata/gVisor 三种均需跑最小执行测试 |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D4.1 | 沙箱服务 | `services/sandbox/` | 服务 | 架构/QA |
| D4.2 | 执行契约 | `packages/contracts` | DTO | 架构 |
| D4.3 | 引擎运行时镜像 | `services/sandbox/runtime/Dockerfile` | 镜像 | DevOps |
| D4.4 | 挂载/启动脚本 | `services/sandbox/runtime/` | 代码 | 架构 |
| D4.5 | 产物校验器 | `services/sandbox/validation/` | 代码 | QA |
| D4.6 | 隔离测试 | `new_app/tests/integration/sandbox/` | 测试 | QA |
| D4.7 | 确定性报告 | `new_app/docs/reports/M4-sandbox-determinism.md` | 报告 | PM/架构 |
| D4.8 | 运行时选型评分报告 | `new_app/docs/reports/M4-runtime-evaluation.md` | 报告 | 项目负责人 |
| D4.9 | K8s 部署清单 | `deploy/k8s/base/sandbox.yaml` | YAML | DevOps |
| D4.10 | 运维说明 | `services/sandbox/README.md` | 文档 | DevOps |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M4-01 | 运行时选型确认 | 架构 | 沙箱/DevOps | 选型记录 | 2026-12-31 |
| M4-02 | Sandbox API 与 DTO | 架构 | 后端 | 契约 | 2027-01-02 |
| M4-03 | 运行时镜像 | 沙箱 | DevOps | 镜像 | 2027-01-04 |
| M4-04 | 挂载与启动 | 沙箱 | 后端 | 执行器 | 2027-01-06 |
| M4-05 | 隔离策略 | 沙箱 | DevOps | 安全配置 | 2027-01-07 |
| M4-06 | 资源/超时/OOM | 沙箱 | DevOps | 限额/错误分类 | 2027-01-08 |
| M4-07 | 产物校验 | 沙箱 | QA | 校验器 | 2027-01-09 |
| M4-08 | 与编排集成 | 后端 | 沙箱 | 真实执行 | 2027-01-11 |
| M4-09 | 隔离/确定性测试 | QA | 沙箱 | 测试报告 | 2027-01-12 |
| M4-10 | 部署与验收 | DevOps | 全体 | 部署清单/验收 | 2027-01-13 |

## 6. 接口与契约

### 6.1 SandboxPort

```python
class SandboxPort(Protocol):
    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
```

### 6.2 ExecutionRequest

必须包含：

- `trace_id/run_id`
- `document`（URI + sha256）
- `ocr`（pages/markdown/layout/tables 引用）
- `recipe`（id/version/digest）
- `template`（id/version/digest）
- `engine_version/image_digest`
- `limits`

### 6.3 ExecutionResult

```json
{
  "status": "succeeded",
  "outputs": {
    "result": "s3://.../result.json",
    "records": "s3://.../records.json",
    "evidence": "s3://.../evidence.jsonl",
    "diagnostics": "s3://.../diagnostics.json"
  },
  "metrics": {"duration_ms": 1234, "memory_mb": 512},
  "manifest": {"engine": "...", "recipe": "...", "template": "..."},
  "diagnostics": []
}
```

### 6.4 挂载约定

```text
/engine              ro
/recipes/{recipe_id} ro
/templates           ro
/input               ro
/output              rw
/tmp                 tmpfs
```

## 7. 安全与隔离要求

| 维度 | 要求 | 验收 |
|---|---|---|
| 网络 | 默认 `none` | 容器内无法访问外网/内网 |
| 文件系统 | 只读 rootfs | 无法写 `/engine`、`/recipes` |
| 用户 | 非 root | `id -u != 0` |
| 能力 | drop all | 无 NET_ADMIN/SYS_ADMIN |
| seccomp | 默认策略 | 禁止危险 syscall |
| 资源 | CPU/内存/PID | 超限被限制/终止 |
| 时长 | 超时 | SIGTERM → SIGKILL |
| 宿主 | 不挂载源码/docker.sock | 无法访问宿主 |

## 8. 验收标准

### 8.1 功能

- [ ] 沙箱可执行无代码配方包（内置解析器）。
- [ ] 沙箱可执行带 entrypoint 的配方包。
- [ ] 按 digest 挂载；同 digest 同输入输出一致。
- [ ] 产物通过 schema/sha256/路径校验。
- [ ] 超时、OOM、非零退出、非法产物分类正确。
- [ ] 编排可调用沙箱并拿到结果。
- [ ] containerd/Kata/gVisor 三种运行时均完成最小执行测试。
- [ ] 运行时评分报告完成，结论回填决策记录 D-007。
- [ ] 选定运行时在 WSL K8s 通过 NetworkPolicy/资源限制验证。

### 8.2 安全

- [ ] 无网络访问。
- [ ] 无宿主文件写入。
- [ ] 非 root。
- [ ] 无危险 capability。
- [ ] 资源限制生效。
- [ ] 容器逃逸测试通过（基础项）。

### 8.3 质量

| 指标 | 门槛 |
|---|---|
| 确定性 | 100% |
| 产物校验 | 100% |
| 隔离测试 | 100% 通过 |
| 超时/OOM | 100% 正确分类 |
| 执行失败可诊断 | 有 error_code + stderr |

### 8.4 文档

- [ ] 沙箱服务 README。
- [ ] 执行契约说明。
- [ ] 镜像构建说明。
- [ ] 安全配置说明。
- [ ] 确定性/隔离报告。

## 9. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K4.1 运行时选型 | 2026-12-31 | 评审通过 |
| K4.2 执行契约冻结 | 2027-01-02 | 架构确认 |
| K4.3 镜像可运行 | 2027-01-04 | 手动执行成功 |
| K4.4 隔离策略完成 | 2027-01-07 | 安全测试通过 |
| K4.5 编排集成 | 2027-01-11 | 真实执行 |
| K4.6 验收 | 2027-01-13 | 报告签字 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| Windows 开发机不支持容器运行时 | 使用 WSL2/远程 Linux 开发环境；CI 用 Linux |
| 运行时选型不确定 | 先用 containerd 默认；Kata/gVisor 作为增强 |
| 镜像过大 | 多阶段构建；基础镜像精简 |
| 沙箱性能不足 | 预热池；资源配额；并行度控制 |
| 产物路径逃逸 | 校验器强制；禁止绝对路径/符号链接 |
| 配方代码恶意行为 | 无网络、只读、非 root、seccomp、资源限制 |

## 11. 出口准则与回滚

**出口准则**

- 沙箱可被编排真实调用。
- 隔离/确定性/错误分类全部通过。
- 安全与架构验收。
- PM 签字。

**回滚**

- 编排可切回 M1 的 fake 沙箱。
- 沙箱服务可独立停用。
- 不影响 M3 配方注册与 M5 Agent。

## 12. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M3](M3-recipe-registry.md)
- 下一里程碑：[M5 Agent Runtime](M5-agent-runtime.md)

## 13. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q3 运行时评分、Q1 WSL K8s、Q8 单人角色 | 项目负责人 |
