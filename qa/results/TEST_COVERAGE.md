# P0+P1+P2 + 文档解析 Phase 1-6 + 整体验收 测试覆盖率统计表

统计口径：覆盖率 = 实际通过用例数 / 计划用例数；单模块通过率必须 ≥95%。
模块全覆盖判定 = 该模块在五层中至少覆盖 3 个层，且所有用例通过。

## 逐模块×层用例数（M1-M23）

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 覆盖层数 | 是否全覆盖 |
|------|--------:|--------:|--------:|--------:|--------:|---------:|---------:|:----------:|
| M1 认证登录 | 8 | 8 | 3 | 5 | 6 | 30 | 5 | 是 |
| M2 密码安全 | 7 | 4 | 1 | 1 | 1 | 14 | 5 | 是 |
| M3 RBAC 角色权限 | 18 | 3 | 4 | 6 | 2 | 33 | 5 | 是 |
| M4 用户管理 | 4 | 7 | 5 | 3 | 2 | 21 | 5 | 是 |
| M5 工作台 | 0 | 5 | 2 | 1 | 0 | 8 | 3 | 是 |
| M6 审计日志 | 0 | 5 | 1 | 0 | 1 | 7 | 3 | 是 |
| M7 个人中心 | 2 | 1 | 2 | 1 | 1 | 7 | 5 | 是 |
| M8 前端路由与菜单权限 | 2 | 2 | 5 | 0 | 0 | 9 | 3 | 是 |
| M9 数据库迁移与种子 | 1 | 5 | 0 | 1 | 0 | 7 | 3 | 是 |
| M10 知识库资源与成员 | 8 | 6 | 6 | 4 | 5 | 29 | 5 | 是 |
| M11 邀请与审批 | 4 | 1 | 1 | 5 | 2 | 13 | 5 | 是 |
| M12 待审批账号 | 1 | 1 | 1 | 0 | 2 | 5 | 4 | 是 |
| M13 工作空间 | 5 | 2 | 2 | 5 | 2 | 16 | 5 | 是 |
| M14 群组并集授权 | 5 | 1 | 1 | 2 | 1 | 10 | 5 | 是 |
| M15 API 密钥 | 2 | 1 | 1 | 2 | 2 | 8 | 5 | 是 |
| M16 审计导出 | 0 | 2 | 1 | 1 | 1 | 5 | 4 | 是 |
| M17 文档解析任务骨架（Phase 1） | 0 | 6 | 1 | 3 | 3 | 13 | 4 | 是 |
| M18 文档解析管线（Phase 2 + 真实权重补测 + UI 改造专项） | 20 | 7 | 9 | 12 | 9 | 57 | 5 | 是 |
| M19 GLM-OCR 拦截层（Phase 3） | 11 | 4 | 2 | 6 | 5 | 28 | 5 | 是 |
| M20 后处理与产物生命周期（Phase 4） | 8 | 4 | 2 | 6 | 5 | 25 | 5 | 是 |
| M21 文档解析前端完整化（Phase 5） | 4 | 2 | 6 | 5 | 5 | 22 | 5 | 是 |
| M22 评测与调优（Phase 6） | 8 | 2 | 1 | 5 | 4 | 20 | 5 | 是 |
| M23 整体验收（Phase 1-6 综合） | 5 | 5 | 2 | 5 | 5 | 22 | 5 | 是 |
| **合计（去重）** | **123** | **84** | **59** | **79** | **63** | **407** | — | **是** |

> 合计含 1 条跨模块复计（L1M9-01 与 L1M3-07 同一幂等种子测试）；
> pytest 329（P0/P1/P2 + Phase1-Phase6 + M23 整体验收 20）+ Playwright/CLI E2E 69
> （P0 20 + P1 11 + P2 5 + 解析 Phase2 4 + Phase3 2 + Phase4 2 + Phase5 16 + Phase6 1 + 整体 2
> + 四项 UI 改造专项 6）
> + node:test 4（M21 L1）+ 迁移脚本 5 = 407。

## 覆盖率结论

- 计划用例数：407
- 实际通过：407（100%）
- 失败/阻塞：0
- 模块全覆盖：22/22（100%）
- **结论：覆盖率 100% ≥ 95%，P0+P1+P2 + 文档解析 Phase 1-6 + 整体验收 + UI 改造专项测试完成。**

## 并发用例清单（铁律第 4 条）

| 编号 | 场景 | 结果 |
|------|------|------|
| L4M1-04 | 10 个并发登录 | 通过 |
| L4M1-05 | 同一刷新令牌并发刷新 | 通过 |
| L4M3-06 | 同一用户并发角色分配（咨询锁） | 通过 |
| L4M4-03 | 并发同名创建（唯一约束转业务错误） | 通过 |
| L4M7-01 | 并发资料更新 | 通过 |
| L4M11-04 | 同一用户并发邀请（唯一约束） | 通过 |
| L4M11-05 | 同一邀请并发接受（行级咨询锁） | 通过 |
| L4M13-05 | 同一用户并发加入工作空间 | 通过 |
| L4M15-02 | 同一 API Key 并发认证 | 通过 |
| L4M18-05 | 同一 KB 并发上传 5 份真实 PDF | 通过 |
| L4M18-06 | 并发重解析（服务层咨询锁） | 通过 |
| L4M18-07 | 并发重解析 API 冒烟 | 通过 |
| L4M19-01 | OCR 全部超时失败记录 | 通过 |
| L4M19-03 | 16 块并发 OCR | 通过 |
| L4M20-03 | 并发页面清理幂等（行级锁） | 通过 |

## 历史隐患复测（铁律第 5 条）

| 编号 | 隐患 | 修复 | 复测结果 |
|------|------|------|:--------:|
| REG-01 | 空邮箱被误判为重复 | user_service 条件修复 | 通过 |
| REG-02 | 过期令牌错误码不精确 | 固定 20002 | 通过 |
| REG-03 | 注册用户无默认角色 | register 自动分配 member | 通过 |
| REG-04 | 并发角色分配唯一约束竞态 | pg_advisory_xact_lock | 通过 |
| REG-05 | 并发同名创建返回 500 | IntegrityError 转业务错误 | 通过 |
| REG-06 | alg=none 未被捕获 | verify_token 捕获 JWSError | 通过 |
| REG-07 | RBAC 种子回填未提交 | ensure_rbac_seed 始终 commit | 通过 |
| REG-08 | 并发接受同一邀请全部成功 | 邀请行级咨询锁+状态重读 | 通过 |
| REG-09 | 成员角色可直接改为 owner | 仅允许所有权转移 | 通过 |
| REG-10 | 审计 details 含 UUID 序列化失败 | 脱敏器支持 UUID/datetime | 通过 |
| REG-11 | OpenAPI/Swagger 生成失败 | 修正 Request 依赖写法（`Request = Depends()` → `Request`） | 通过 |
| REG-12 | 邀请时角色被操作者角色覆盖 | 权限校验改用独立变量名 | 通过 |
| REG-13 | Vite 代理 `/api` 误拦截 `/api-keys` | 代理前缀改为 `/api/` | 通过 |
| REG-14 | 邀请/初始成员可授予 owner 角色 | KbInviteCreate/KbMemberSeed 禁止 owner | 通过 |
| REG-15 | RLS 空 app.user_id 强转 uuid 报错 | 006 迁移 + hansondoc_current_user() 返回 NULL | 通过 |
| REG-16 | DocLayout-YOLO 权重为 fp16 且含自定义 Detect 头 | 加载后 model.float() + weights_only=False（来源可信已锁 SHA256） | 通过 |
| REG-17 | doclayout_yolo 0.0.4 与 ultralytics 8.4 不兼容（Conv.bn） | 固定 ultralytics==8.1.47 并采用手动推理（letterbox→forward→NMS） | 通过 |
| REG-18 | 页眉版面块被识别为表格混入 OCR 产物 | 版面块页边距过滤（top≤16%/bottom≥84%，封面保留） | 通过 |
| REG-19 | 并发清理重复处理同一文档 | cleanup 查询加 FOR UPDATE SKIP LOCKED 行级锁 | 通过 |

## 产物清单

- 用例文档：[qa/TEST_CASES.md](../TEST_CASES.md)
- 测试铁律：[qa/TESTING_PROCESS.md](../TESTING_PROCESS.md)
- 后端测试：`qa/unit`、`qa/integration`、`qa/boundary`、`qa/security`
- 前端 E2E：`qa/functional/e2e_p0.mjs`、`e2e_p1.mjs`、`e2e_p2.mjs`、`e2e_phase2.mjs`、`e2e_phase3.mjs`、`e2e_phase4.mjs`、`e2e_phase5.mjs`、`e2e_phase5_boundary.mjs`、`e2e_phase5_security.mjs`
- 前端 L1：`qa/unit/test_frontend_phase5.mjs`（node:test）
- Phase 6 评测：`qa/evaluation/generate_samples.py`、`metrics.py`、`evaluate_phase6.py`、`reports/`、`ground_truth/`
- 整体验收：`qa/unit|integration|boundary|security/test_overall_acceptance_*`、`qa/functional/e2e_overall_acceptance.mjs`
- 迁移验证：`qa/migration/verify_migration.sh`
- 截图归档：`qa/results/p0_*.png`、`p1_*.png`、`p2_*.png`、`parsing_phase2_*.png`、`parsing_phase3_*.png`、`parsing_phase4_*.png`、`parsing_phase5_*.png`
- DocLayout-YOLO 权重：`models/doclayout_yolo/doclayout_yolo.pt`（SHA256 `1b152460...c80be`，不入 Git）
- U3 A/B 评测：`qa/evaluation/header_footer_ab/`（report.md、annotations.json、enhanced_strategy.py 归档）
- 历史脚本归档：`qa/legacy/`
