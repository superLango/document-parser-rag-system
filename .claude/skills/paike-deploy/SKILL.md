---
name: paike-deploy
description: 派克 / 汉唐盒子的离线部署，以及配套的分支、push、PR 操作。用户说“部署派克盒子”“部署到派克”“更新派克”“打派克更新包”“汉唐也同步一下”“部署汉唐 01”，或提到派克盒子、192.168.70.161、离线部署、.run 更新包、wjh-pr / wjh-doc_parse 怎么 push、怎么提 PR、要改离线部署脚本时使用。
---

# 派克 / 汉唐盒子离线部署

先完整读 `new_app/deploy/offline/PAIKE.md`（架构、端口、目录、镜像、分支约定、各类改动的部署方式、脚本扩展规则）。

## 分支约定（仓库 `F:\work\RAG_doc_parse`，远程 superLango/document-parser-rag-system）

| 分支 | 放什么 | 用来 |
|---|---|---|
| `wjh-pr` | `new_doc_parse` + 要给团队的功能 / 修复 | 开发、push、向 `new_doc_parse` 提 PR |
| `wjh-doc_parse` | `wjh-pr` 的全部 + 个人内容（`new_app/deploy/offline/`、`dict/`、`.claude/skills/`）| 打离线部署包 |

- 功能 / 修复提交在 `wjh-pr`；部署脚本、词典、skill 只提交在 `wjh-doc_parse`。**永远不要把 `wjh-doc_parse` 合进 `wjh-pr`**（会把个人内容和派克数据带进 PR）。
- AI 在 `wjh-doc_parse` 上改了功能代码时：`git stash push -- <文件>` → `git switch wjh-pr` → `git stash pop` → 提交 → `git switch wjh-doc_parse` → `git merge wjh-pr`。
- 要不要先 `git pull origin new_doc_parse`：只在用户要用团队最新代码时做。拉下来的提交可能带新的解析内核（lango 的 parser_core 版本），这时派克要加 `--parser`，见下文。
- 提交作者是 Hui2019-1（全局 git 配置）。**push 和 PR 用户想自己操作：AI 只给指令**，除非用户明确让 AI 来做。

## 用户说“部署派克盒子”这类话时

用户的习惯：**AI 只给出要运行的指令，用户自己插上内网网线去执行**。不要自己去连派克盒子，除非用户明确要求（例如盒子临时放在外网 192.168.185.236，并让 AI 操作）。

1. 看状态：`git status --short`、`git log --oneline origin/new_doc_parse..wjh-pr`、`git log --oneline -3 wjh-doc_parse`，以及记忆里“上次部署到派克的包 / 提交”。
   有未提交的功能改动 → 先按上面的分支约定提交到 `wjh-pr` 并合进 `wjh-doc_parse`（包名不带 `-dirty`）。
2. 按自上次部署以来改动的文件决定打包类型：只有 `new_app/web/**` → `web`；只有 `services|packages|tests` → `app`；都有 → `all`。
   解析内核有变化（`services/sandbox/runtime/**`、lango 发了新 parser_core 版本、或 `dict/pk/dictionary_data.json` 变了）→ 加 `--parser <派克新版本> --dict pk`（版本表见 PAIKE.md 6.2，先查盒子当前 stable，按 1.7.9xx 递增）。只重启 recipe-registry 不会换版本。
   改了 `requirements.txt`、`deploy/compose/nginx.conf`、compose、`.env`、编排侧 `business_dictionary.json` → 脚本不覆盖，按 PAIKE.md 第 6 节单独给出步骤。
3. AI 在 `wjh-doc_parse` 上先把包打好（Git Bash：`bash new_app/deploy/offline/make_bundle.sh <类型> [--parser … --dict pk]`），确认产物文件名后再给指令。
4. 按下面的模板回复，命令里填好真实的包名，每条命令单独一个代码块（cmd 用 `bat`）：

```text
本次改动：<一两句，列出提交>；打包类型：<web|app|all>[+解析内核]（<是否会重启后端、会不会打断解析任务>）

① 本地分支（AI 已做好可跳过；用户自己改过代码时要做）
   cd /d F:\work\RAG_doc_parse
   git switch wjh-doc_parse
   git merge wjh-pr
② 本地打包（已打好可跳过）
   new_app\deploy\offline\make_bundle.cmd <类型> [--parser <版本> --dict pk]
③ 插内网网线后上传
   ssh yzling@192.168.70.161 "mkdir -p ~/doc-parse-deploy"
   scp F:\work\RAG_doc_parse\new_app\deploy\offline\out\<包名>.run yzling@192.168.70.161:/home/yzling/doc-parse-deploy/
④ 部署
   ssh yzling@192.168.70.161 "bash ~/doc-parse-deploy/<包名>.run"
⑤ 验证：输出末尾 网关=200 页面=200、前端版本 index-xxxx.js[、解析内核 stable: <版本>]；浏览器打开 http://192.168.70.161:18080 按 Ctrl+F5，<说明本次要检查的具体功能>
⑥ 出问题回滚
   ssh yzling@192.168.70.161 "bash ~/doc-parse-deploy/<包名>.run rollback"
⑦ 推送与 PR（见下节，本次有新功能提交时才需要）
```

   附带提醒：含后端（app/all）时要等解析任务空闲（脚本会拦截）；连不上时检查本机代理 TUN（见 PAIKE.md 第 2 节）；网络不稳时先 `ssh` 登录再在盒子上执行 `.run`；实在不行用 U 盘拷 `.run` 到盒子后在盒子终端执行 `bash <包名>.run`。
5. 用户回报部署结果后，把“已部署到派克的提交 / 包名 / 日期”记下来（更新记忆），下次据此判断改动范围。

## 汉唐 01 同步（用户说“汉唐也同步一下”）

- 01（`htjiance8@193.168.2.201`）一直在内网可直连，部署目录、端口和派克相同，同一个 `.run` 包可以直接用。**AI 可以直接部署**：`scp` 到 `~/doc-parse-deploy/`，再 `ssh … "bash ~/doc-parse-deploy/<包名>.run < /dev/null"`，然后核对页面和接口。
- 带解析内核时 01 用 `--dict ht` 另打一个包（`pk` 包装到 01 会被脚本拒绝）；汉唐直接沿用 lango 的版本号（如 1.7.41）。
- 部署后把“已部署到 01 的包 / 提交 / 日期”记下来。

## 推送与 PR（给用户的指令）

本次有新的功能 / 修复提交在 `wjh-pr` 上时，给出：

```text
cd /d F:\work\RAG_doc_parse
git push origin wjh-pr
git push origin wjh-doc_parse
E:\codex_home\tools\gh-cli\bin\gh.exe pr create --repo superLango/document-parser-rag-system --base new_doc_parse --head wjh-pr --title "<标题>" --body "<改了什么、为什么、在哪台盒子验证过>"
```

- 先查有没有未合并的 PR：`gh pr list --repo superLango/document-parser-rag-system --head wjh-pr --state open`。**已有就不用再建**，push 之后新提交会自动进到那个 PR；没有才 `gh pr create`。
- 只改了个人内容（部署脚本、词典、skill）时，只需要 `git push origin wjh-doc_parse`，不提 PR。
- lango 合并 PR 之后：`git switch wjh-pr` → `git pull origin new_doc_parse`，再 `git switch wjh-doc_parse` → `git merge wjh-pr`。
- 不要删除还挂着未合并 PR 的远程分支（删掉 PR 会被自动关闭）。
- 用户的 `new_doc_parse` 上 CI 的 python 检查本来就失败（已有代码的 ruff 问题），web 检查通过即可。

## 改离线部署脚本时

改了 `make_bundle.sh` / `install.sh` 后，必须用 `make_bundle.sh all --parser 1.7.999 --dict pk` 打包并跑 `bash new_app/deploy/offline/selftest.sh <该 .run>` 全部通过；新增能力同时补 selftest 用例和 PAIKE.md 第 6、7 节。

## 约束

只用公钥 SSH，不输入任何密码 / sudo 密码；不打印 `.env`；不删 `hansondoc-backend:latest`、`hanson-new-app:base`、老项目 `~/hansonDoc_RAG` 的数据卷；不碰模型进程；不要把脚本通过管道喂给 `ssh … bash -s`（里面的 `docker exec -i` 会吞掉剩下的脚本），先 `scp` 再执行；盒子事实与 PAIKE.md 不符时以 `docker ps` / `docker inspect` 为准并更新 PAIKE.md。
