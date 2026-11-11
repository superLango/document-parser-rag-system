# Hanson 标准拆分平台

本仓库正在执行标准拆分平台重构。当前有效代码全部位于 `new_app/`，旧系统代码已归档到 `legacy/`，仅作为实现参考，不参与新架构构建。

## 目录

| 目录 | 说明 |
|---|---|
| `new_app/` | 本次重构的唯一代码目录：前后端、服务、契约、部署、测试 |
| `new_app/docs/` | 正式架构方案、需求、决策记录、整体计划与 M0–M8 里程碑计划 |
| `legacy/` | 旧系统归档，只读参考；不 import、不修改、不参与构建 |

## 当前阶段

M0：基础架构脚手架。已完成目录、服务健康检查骨架、契约占位、前端骨架、Compose 与 CI；业务逻辑尚未实现。

## 快速开始

```powershell
cd new_app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn services.api_gateway.main:app --reload --port 8000
```

前端：

```powershell
cd new_app/web
npm install
npm run dev
```

基础设施：

```powershell
cd new_app
docker compose -f deploy/compose/docker-compose.yml up -d
```

## 文档

- [架构重构方案](new_app/docs/architecture-refactor-plan.md)
- [项目需求文档](new_app/docs/requirements.md)
- [项目决策记录](new_app/docs/decision-log.md)
- [整体开发计划](new_app/docs/development-plan.md)
- [M0 执行计划](new_app/docs/M0-project-scaffold.md)

## 分支

当前重构分支：`new_doc_parse`
