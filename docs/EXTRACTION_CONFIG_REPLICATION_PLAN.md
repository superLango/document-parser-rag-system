# 抽取配置四项功能阶段性复刻方案（Schema / Prompt / 规则 / 脚本）

> 依据：[EXTRACTION_CONFIG_RESEARCH.md](./EXTRACTION_CONFIG_RESEARCH.md)（原项目前端+接口调研）
> 原则：功能复刻原项目，UI/动效按当前项目浅绿白规范；冗余无效代码一律不迁移；
> 每阶段按 `qa/TESTING_PROCESS.md` 铁律完成五层测试并归档。

## 1. 复刻范围

本期复刻 4 项：

| 模块 | 原项目对应 | 本期范围 |
|------|-----------|----------|
| Schema 模板 | 模板→类别→字段三层结构 | 完整 CRUD；类别高级配置（名称来源手动/术语集、返回类型、抽取策略、固定 Query、Query 术语集、类别级覆盖、启用） |
| Prompt 模板 | 模板列表 + PromptEditor | 模板 CRUD（simple/schema 模式、绑定 Schema 与类别）；编辑页 system + 按类别 user 提示词、字段/系统参数占位符、术语集参数引用、渲染预览 |
| 后处理与校验规则 | 规则组按类别绑定规则项 | 规则组 CRUD、按类别绑定脚本规则项（脚本名+参数 JSON）、启用/排序 |
| 脚本管理 | ScriptManager | post/validation 两目录脚本 CRUD、IO 注册、代码编辑、调试运行（受限执行） |

## 2. 记录项（本期不做，四项完成后另行方案）

1. **全局配置**（检索五维权重/hybrid/reranker/context、LLM 引擎参数、KB 工具参数）：
   依赖当前项目 LLM/嵌入/检索体系（LLM 兼容层待定、嵌入/重排待三方比较），
   建议与抽取执行阶段一并建设；当前不建表不建页面。
2. **版本管理**（配置快照/diff/回滚）：
   依赖四模块配置结构稳定后做统一快照，建议四项完成后作为“配置版本治理”统一设计。

## 3. 技术约束（硬性）

- 前端：React + 浅绿白主题，复用现有组件（Card/Table/Dialog/Select/Input/PageHeader/Pagination）；
  缺少的通用组件（Switch、Tabs、Textarea 封装）按需在 `frontend/src/components/ui/` 新增并复用，禁止页面内重复实现；
- 后端：PostgreSQL + RLS（沿用 010 模式）、软删/硬删按最终语义（当前术语集为硬删）、
  权限 viewer 只读 / editor+ 管理、审计日志；
- 冗余剔除（迁移审查清单强制项）：
  - 不迁移原项目未选中的能力：regex rules、field templates、prompt categories、bindings、validation 独立表、
    旧引擎兼容映射（glmocr→BaseExtract 等）、Config.vue（资源与配置）、TestPanel 真实 LLM 调用；
  - 每阶段交付前检查：无未使用 import/死分支/调试残留/整体复制；
  - 测试同样审查，禁止 noop 占位。

## 4. 数据模型草案（迁移 012，全部 kb_id + RLS）

```text
schema_templates
  id / kb_id / name / description / is_active / sort_order
  created_by / created_at / updated_at

schema_categories
  id / kb_id / template_id(FK cascade) / name / description
  return_type(array|object) / extraction_strategy(auto|always|never)
  fixed_query / confidence_threshold / top_k / rerank_top_k / max_tokens
  name_source(manual|term_base) / name_term_base_id(FK term_bases) / name_term_field
  query_sources(JSONB)      -- [{label, term_base_id, group_field, value_field, in_query, dedupe, query_main_limit, query_refined_limit}]
  is_active / sort_order / created_at / updated_at

schema_fields
  id / kb_id / category_id(FK cascade) / name / type(string|number|boolean|array)
  description / example / required / sort_order / created_at / updated_at

prompt_templates
  id / kb_id / name / description / scope(simple|schema) / schema_template_id(FK)
  category_ids(JSONB) / is_active / created_by / created_at / updated_at

prompt_content
  id / kb_id / prompt_id(FK cascade) / category_id(可空=simple) / system_prompt / user_prompt
  updated_at

rule_groups
  id / kb_id / name / enabled / sort_order / created_at / updated_at

rule_group_items
  id / kb_id / group_id(FK cascade) / category_id(可空=全局) / script_name
  params(JSONB) / enabled / sort_order / created_at / updated_at

kb_scripts
  id / kb_id / folder(post|validation) / name / description / enabled / code / created_by / created_at / updated_at
```

说明：
- 脚本**执行**（runScript 调试）本期做受限执行：同进程 eval/exec 有安全风险，
  建议独立子进程 + 超时 + 无网络，工具（kb_tools）本期仅提供术语集读取桩与静态校验，
  真实工具（检索/嵌入）在抽取阶段接入；
- Query 术语集联动复用现有 `term_base_loader`（分组+缓存+active 过滤）。

## 5. 分阶段实施计划（每阶段铁律验收）

### S1 数据模型与迁移
- 新增 `012_extraction_config.py`：上表 + 索引 + RLS（复用 010 策略模式）；
- `app/models/extraction.py` 模型注册；
- 测试 M34-S1：迁移幂等/RLS/模型约束/唯一性（L1/L2/L4）。

### S2 后端 API
- `app/api/v1/endpoints/kb_extraction_config.py`：
  - Schema：模板/类别/字段 CRUD（级联删除、重名校验、editor+ 权限）
  - Prompt：模板 CRUD + 内容保存（simple/schema）
  - 规则：规则组 CRUD + 组内规则项批量保存
  - 脚本：目录/CRUD + IO registry + runScript（受限子进程 + 超时 + 日志）
- 测试 M34-S2：L1-L5（权限/隔离/级联/上限/脚本超时/并发保存）。

### S3 前端 Schema 模板页
- 组件：模板列表 + 模板/类别/字段三层树状编辑器、类别与字段弹窗（含术语集联动下拉）；
- 路由：`extraction-config` 单页 4 页签（Schema/Prompt/规则/脚本），对齐原项目页签结构；
- 测试 M34-S3：tsc/build + E2E（模板→类别→字段闭环、术语集名称来源、Query 术语集、移动端）。

### S4 前端 Prompt 模板页 + 编辑器
- 列表/新建（simple/schema 绑定 Schema 与类别）+ 独立编辑路由 `extraction-config/prompts/:id`：
  simple 上下布局；schema 三栏（类别/user 提示词/字段占位符插入）+ 术语集参数引用；
  提供“渲染预览”（替换占位符，不调 LLM）；
- 测试 M34-S4：E2E（创建/绑定/占位符/保存/权限）。

### S5 前端后处理与校验规则页
- 规则组 CRUD + 组内按类别添加规则项（脚本名来自脚本管理 + 参数 JSON 表单）+ 启用/排序；
- 测试 M34-S5：E2E（组/规则项/类别绑定/删除级联）。

### S6 前端脚本管理页
- 左中右布局：目录（post/validation）+ 脚本列表/编辑 + IO 参数与工具目录 + 底部调试（args→run→结果）；
- 测试 M34-S6：E2E（新建/编辑/启用/调试运行/失败提示/权限）。

### S7 整体验收
- 四项联动真实链路（Schema→Prompt→规则绑定脚本→脚本调试→术语集引用）；
- M34 全量五层 + 覆盖率统计表 + 帮助文档更新 + 迁移审查清单。

## 6. 与术语集/后续抽取的联动

- 类别名称来源术语集、Query 术语集：配置期写入 JSONB/FK，执行期由 `term_base_loader` 消费；
- 脚本工具 `get_term_records`：S6 先提供只读术语集访问桩，抽取阶段替换为真实工具目录；
- Prompt 渲染预览：本期做占位符替换预览，LLM 实际调用待抽取执行阶段。

## 7. 待确认问题

1. **页面形态**：四项是否做“抽取配置”单页 4 页签（对齐原项目），Prompt 编辑独立路由？推荐：是。
2. **脚本执行安全**：runScript 调试本期允许在受限子进程执行用户 Python（超时/无网络），还是仅保存+静态校验不执行？推荐：受限子进程执行（含术语集读取桩）。
3. **Schema 类别“名称来源术语集 / Query 术语集”**：本期完整复刻配置能力（含校验），执行在抽取阶段？推荐：是。
4. **Prompt 调试**：本期只做“渲染预览”（替换占位符），不做 LLM 试跑？推荐：是。
5. **版本管理**：确认本期不做、四项完成后单独方案？推荐：是。
6. **全局配置**：确认本期不做（依赖 LLM/检索体系确定后）？推荐：是。
7. **脚本目录**：仅 post/validation 两类（对齐原项目）？推荐：是。
8. **规则项脚本来源**：规则项只能选择脚本管理中已存在的脚本，还是允许自由填写脚本名？原项目为自由填写；推荐：自由填写+校验存在性提示（对齐原项目）。
9. **术语集联动范围**：脚本调试中 `get_term_records` 是否允许真实读取当前 KB 术语集（只读）？推荐：允许（本地只读，无网络）。
10. **菜单/占位**：抽取配置菜单入口继续使用现有“抽取配置”位置，页面替换占位为 4 页签？推荐：是。
