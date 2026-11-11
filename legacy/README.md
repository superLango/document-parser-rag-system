# Legacy 归档

本目录保存重构前的旧系统代码与文档，仅作为实现参考。

规则：

- 不修改、不 import、不参与 `new_app` 构建。
- 可复用的逻辑必须复制到 `new_app/` 后重写，并记录到 `new_app/PROVENANCE.md`。
- 旧数据、旧产物、旧接口不作为新系统运行时依赖。
- 旧系统在 M8 切换完成并稳定后可按归档策略清理。

目录对应：

| 归档目录 | 原位置 |
|---|---|
| `legacy/apps/` | `apps/` |
| `legacy/metal-doc-agent/` | `metal-doc-agent/` |
| `legacy/packages/` | `packages/` |
| `legacy/e2e/` | `e2e/` |
| `legacy/infra/` | `infra/` |
| `legacy/deploy/` | `deploy/` |
| `legacy/docs/` | `docs/` |
| `legacy/training/` | `training/` |
| `legacy/metal-standard-agent-plan/` | `metal-standard-agent-plan/` |
| `legacy/markdown/` | `markdown/` |
| `legacy/root/` | 旧根配置（package.json、pnpm、README、.dockerignore） |
| `legacy/.github/workflows/ci.yml` | 旧 CI |
