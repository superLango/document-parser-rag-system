---
name: paike-deploy
description: 派克（Paike）客户盒子的架构与离线部署。用户说“部署派克盒子”“部署到派克”“更新派克”“打派克更新包”，或提到派克盒子、192.168.70.161、离线部署、.run 更新包、要改离线部署脚本时使用。
---

# 派克盒子离线部署

先完整读 `new_app/deploy/offline/PAIKE.md`（架构、端口、目录、镜像、各类改动的部署方式、脚本扩展规则）。

## 用户说“部署派克盒子”这类话时

用户的习惯：**AI 只给出要运行的指令，用户自己插上内网网线去执行**。不要自己去连盒子部署，除非用户明确要求。

0. 分支约定（PAIKE.md 5.0）：功能在 `wjh-pr` 开发并向 `new_doc_parse` 提 PR；打包在 `wjh-doc_parse`，先 `git merge wjh-pr`。指令里要包含切分支和合并这两步。
1. 在本地仓库 `F:\work\RAG_doc_parse` 看状态：`git status --short new_app`、`git log --oneline origin/new_doc_parse..HEAD`，以及上次部署的提交（PAIKE.md / 记忆里有记录则用，没有就问用户或按“上次部署之后的所有提交”估算）。
   有未提交改动 → 先问用户是否提交（包名会带 `-dirty`）。
2. 按改动的文件决定打包类型：只有 `new_app/web/**` → `web`；只有 `services|packages|tests` → `app`；都有 → `all`。
   改了 `requirements.txt`、`deploy/compose/nginx.conf`、compose、`.env`、词典 / 解析内核 → 脚本不覆盖，按 PAIKE.md 第 6 节单独给出步骤。
3. 可以由 AI 先在本地打好包（`new_app\deploy\offline\make_bundle.cmd <类型>`，或 Git Bash 下 `bash new_app/deploy/offline/make_bundle.sh <类型>`），确认产物文件名后再给指令；也可以把打包命令一并交给用户。
4. 按下面的模板回复，命令里填好真实的包名，每条命令单独一个代码块：

```text
本次改动：<一两句，列出提交>；打包类型：<web|app|all>（<是否会重启后端、会不会打断解析任务>）

① 本地打包（cmd，已打好可跳过）
   cd /d F:\work\RAG_doc_parse
   new_app\deploy\offline\make_bundle.cmd <类型>
② 插内网网线后上传（cmd）
   ssh yzling@192.168.70.161 "mkdir -p ~/doc-parse-deploy"
   scp F:\work\RAG_doc_parse\new_app\deploy\offline\out\<包名>.run yzling@192.168.70.161:/home/yzling/doc-parse-deploy/
③ 部署
   ssh yzling@192.168.70.161 "bash ~/doc-parse-deploy/<包名>.run"
④ 验证：输出末尾 网关=200 页面=200、前端版本 index-xxxx.js；浏览器打开 http://192.168.70.161:18080 按 Ctrl+F5，<说明本次要检查的具体功能>
⑤ 出问题回滚
   ssh yzling@192.168.70.161 "bash ~/doc-parse-deploy/<包名>.run rollback"
```

   附带提醒：含后端（app/all）时要等解析任务空闲（脚本会拦截）；连不上时检查本机代理 TUN（见 PAIKE.md 第 2 节），实在不行用 U 盘拷 `.run` 到盒子后在盒子终端执行 `bash <包名>.run`。
5. 用户回报部署结果后，把“已部署到派克的提交 / 包名 / 日期”记下来（更新记忆），下次据此判断改动范围。

## 改离线部署脚本时

改了 `make_bundle.sh` / `install.sh` 后，必须用 `make_bundle.sh all` 打包并跑 `bash new_app/deploy/offline/selftest.sh <*-all.run>` 全部通过；新增能力同时补 selftest 用例和 PAIKE.md 第 6、7 节。

## 约束

只用公钥 SSH，不输入任何密码 / sudo 密码；不打印 `.env`；不删 `hansondoc-backend:latest`、`hanson-new-app:base`、老项目 `~/hansonDoc_RAG` 的数据卷；不碰模型进程；盒子事实与 PAIKE.md 不符时以 `docker ps` / `docker inspect` 为准并更新 PAIKE.md。
