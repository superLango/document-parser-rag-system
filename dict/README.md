# 业务词典（按客户维护）

| 目录 | 客户 | 部署在 | 当前解析内核 |
|---|---|---|---|
| `ht/` | 汉唐 | 01（193.168.2.201） | parser_core **1.7.40** |
| `pk/` | 派克 | 派克盒子（192.168.70.161） | parser_core **1.7.901** |

代码两边完全相同，只有词典不同。仓库代码里自带的是**汉唐**词典：

- `new_app/services/orchestration/data/dictionary/business_dictionary.json`，与 `ht/business_dictionary.json` 相同；
- `new_app/services/recipe_registry/.../parser_core/1.7.40/dictionary_data.json`，与 `ht/dictionary_data.json` 相同。

派克词典只在派克盒子上，通过发布 parser_core 1.7.900、1.7.901 生效。这里是它的源文件和产物。

## 文件

每个目录有两个产物：

- `business_dictionary.json`：编排服务的业务词典，也是词典页面显示的数据。盒子路径为 `deploy-package/data/orchestration/dictionary/business_dictionary.json`。
- `dictionary_data.json`：解析内核里的精简词典，由上一个文件生成，随 parser_core 版本一起发布。

`pk/` 下还有生成派克词典用的源文件：

| 文件 | 作用 |
|---|---|
| `业务词表new.txt` | 派克 LIMS 导出（sm_item / sm_method）：检测项目、试验方法与项目大类，是权威来源 |
| `old_terms.json` | 派克旧系统数据库术语库里的别名、方法标题，用来补别名 |
| `build_paike_dictionary.py` | 转换脚本：txt 加汉唐基线，生成派克 `business_dictionary.json`。一个检测项目属于多个大类时拆成多条 |
| `歧义别名清单.csv` | 80 个指向多个项目的歧义别名（如 Rp0.2、KV2），等业务方确认 |

汉唐词典的源头是 `legacy/metal-doc-agent/configs/dictionaries/`（由汉唐 xlsx 拆分而来）。

## 更新派克词典

1. 用新的 LIMS 导出覆盖 `pk/业务词表new.txt`，然后重新生成两个产物：

```bash
python dict/pk/build_paike_dictionary.py dict/pk/业务词表new.txt dict/ht/business_dictionary.json dict/pk/business_dictionary.json new_app dict/pk/old_terms.json
python new_app/scripts/assets/build_dictionary_asset.py --source dict/pk/business_dictionary.json --target dict/pk/dictionary_data.json
```

2. 提交 `dict/pk/`。
3. 上盒子需要做两件事：
   - 解析内核：`new_app\deploy\offline\make_bundle.cmd all --parser <新版本> --dict pk` 打包，盒子上执行 `.run`。它会发布新版本并设为 stable，详见 `new_app/deploy/offline/PAIKE.md` 6.2 节；
   - 编排侧词典：把 `pk/business_dictionary.json` 替换到盒子的 `data/orchestration/dictionary/business_dictionary.json`，再重启 orchestration。这一步脚本不做。

2026-11-17 已验证：用本目录的文件运行上面的命令，生成的结果与 `pk/` 里的产物逐条一致。

## 改了解析内核代码之后

仓库发布的新内核版本带的是汉唐词典。汉唐直接用即可。派克要在同一份代码上换成 `pk/dictionary_data.json`，再单独发布一个版本，否则派克会继续停在旧内核上。
