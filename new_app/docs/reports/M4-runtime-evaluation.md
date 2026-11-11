# M4 运行时选型评分报告

> 文档版本：v1.0  
> 编制日期：2026-11-11  
> 所属里程碑：[M4 沙箱服务与执行引擎](M4-sandbox-runtime.md)  
> 结论：默认采用 **containerd + runc**；gVisor 作为可选加固 profile；Kata 本期不选。

---

## 1. 结论摘要

| 项 | 结论 |
|---|---|
| 默认运行时 | containerd + runc（Docker/Compose 与 K8s 均验证） |
| 可选加固运行时 | gVisor（runsc，KVM 平台） |
| Kata Containers | 本期不选；本机无 kata-runtime/QEMU，静态包 1.02 GB 且下载超时，未完成执行验证 |
| 选型依据 | 安全性 30%、资源开销 25%、兼容性 25%、运维复杂度 20% |
| 加权得分 | runc 9.10、gVisor 7.65、Kata 6.55（Kata 为纸面评分，未实测） |
| 决策回填 | [decision-log D-007](decision-log.md#d-007-沙箱运行时按多维度评估选择) |

选型理由：

- 配方代码来自内部受控注册中心，默认 runc 已满足无网络、只读 rootfs、非 root、cap drop、seccomp 与资源限制要求，兼容性与运维成本最优。
- 对后续可能引入的第三方/不可信配方，gVisor 可在节点注册 runsc 后通过 `SANDBOX_RUNTIME=runsc` 切换，无需修改执行契约。
- Kata 的 VM 隔离收益在“内部配方”场景下不足以抵消 QEMU/KVM、节点配置、镜像与排障成本；生产多租户阶段再以 kata-deploy 重新评估。

---

## 2. 评估环境

| 项 | 值 |
|---|---|
| 宿主 | Windows 11 + WSL2（Ubuntu 24.04.4 LTS） |
| Docker | 29.7.2，默认 runtime `runc`，已注册 `io.containerd.runc.v2` |
| gVisor | Ubuntu 包 `runsc 0.0~20230807.0`，spec 1.1.0 |
| K8s | kind v0.24.0 + kindest/node:v1.30.0，集群 `hanson` |
| 虚拟化 | `/dev/kvm` 存在，gVisor KVM 平台可用 |
| 引擎镜像 | `hanson-sandbox-runtime:local`（python:3.12-slim，非 root，只读 /engine） |
| 沙箱镜像摘要 | 以 `GET /images/...` 返回的 `Id` 为准，每次执行写入 manifest |

---

## 3. PoC 方法与结果

复现脚本：[runtime-poc.sh](../../scripts/dev/runtime-poc.sh)、[runtime-bench.sh](../../scripts/dev/runtime-bench.sh)。

### 3.1 runc（基线，必测）

```bash
docker run --rm --runtime=runc --network none --read-only --user 65534:65534 \
  --cap-drop ALL --security-opt no-new-privileges --memory 128m --cpus 0.5 \
  --pids-limit 64 --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --entrypoint sh hanson-sandbox-runtime:local -c '...'
```

实测输出：

```text
uid=65534
cap_eff=0000000000000000
engine_write=denied (Read-only file system)
tmp_write=allowed
network=blocked
```

结论：非 root、零有效 capability、rootfs 只读、无网络、tmpfs 可写，全部符合硬性要求。

### 3.2 gVisor（加固候选）

```bash
runsc --network=none --platform=kvm do sh -c 'id -u; ...'
```

实测输出：

```text
runsc version 0.0~20230807.0
spec: 1.1.0
uid=0
network=blocked
tmp_write=allowed
gvisor_nonroot_uid=65534
```

说明：

- `runsc do` 默认以宿主 root 身份启动沙箱，用于验证运行时本身；另用 `su nobody` 在沙箱内验证非 root 用户（`uid=65534`）可运行。
- 生产接入 Docker/K8s 时仍由 OCI 配置设置 `user=65534`、`readonly`、`cap-drop`。
- WSL2 的 `/dev/kvm` 可用，KVM 平台启动成功。
- Docker Desktop 的 dockerd 未注册 runsc，因此本次未做 `docker run --runtime=runsc`；节点注册方式已写入 README。

### 3.3 Kata Containers（本期环境受限）

| 检查项 | 结果 |
|---|---|
| `command -v kata-runtime` | 未安装 |
| `apt-cache policy kata-containers` | Ubuntu 24.04 仓库无候选 |
| `qemu-system-x86_64` | 未安装 |
| Kata 4.3.1 静态包 | `kata-static-4.3.1-amd64.tar.zst` 约 1.02 GB；GitHub 下载 20 s 超时，未完成 |
| `kata-tools-static` | 约 21 MB，仅工具，不含 VM 内核/镜像与 QEMU |

结论：本机无法在合理时间内完成 Kata 最小执行测试。**不把未验证项当作通过**；Kata 评分仅作纸面参考，不参与最终选型。生产 K8s 若需要 VM 级隔离，建议用 `kata-deploy` 在具备嵌套虚拟化的节点池单独验证。

---

## 4. 评分矩阵

评分采用 0–10 分，加权总分 = Σ(维度得分 × 权重)。

| 维度 | 权重 | runc | gVisor | Kata | 说明 |
|---|---:|---:|---:|---:|---|
| 安全性 | 30% | 7 | 10 | 10 | runc 共享内核；gVisor 用户态内核；Kata VM 隔离 |
| 资源开销 | 25% | 10 | 6 | 3 | runc 原生；gVisor syscall 拦截；Kata VM 启动/内存 |
| 兼容性 | 25% | 10 | 7 | 8 | gVisor 对部分 syscall/GPU/io_uring 支持有限；Kata 依赖 KVM |
| 运维复杂度 | 20% | 10 | 7 | 4 | gVisor 需节点注册；Kata 需 QEMU/KVM、镜像与节点池 |
| **加权总分** | **100%** | **9.10** | **7.65** | **6.55\*** | \*Kata 未实测 |

计算过程：

- runc：7×0.30 + 10×0.25 + 10×0.25 + 10×0.20 = **9.10**
- gVisor：10×0.30 + 6×0.25 + 7×0.25 + 7×0.20 = **7.65**
- Kata：10×0.30 + 3×0.25 + 8×0.25 + 4×0.20 = **6.55**

---

## 5. 资源开销实测

| 场景 | 耗时 | 备注 |
|---|---:|---|
| runc 容器冷启动（带隔离参数，`true`） | 914 / 930 / 960 ms | Docker CLI + daemon + 容器创建 |
| gVisor `runsc do true` | 209 / 277 / 337 ms | 独立沙箱创建，不含 Docker 镜像路径，不可直接对比 |
| 真实沙箱执行（runc，解析 2 行表格） | 509 ms | 含工作区准备、容器执行、产物归档 |
| Compose 全链路沙箱阶段 | 937–1066 ms | 含 HTTP、对象存储、校验、上传 |
| K8s Job 沙箱阶段 | 5527 ms | 含 Job/Pod 调度、ConfigMap、init 容器、日志回传 |

内存：

- 真实执行 `peak_memory_mb=23`（引擎解析小样本），限制 256 MB。
- Docker OOM 测试：64 MB 限制下分配 20 MB/轮，容器被 cgroup OOM kill，`OOMKilled=true`。
- K8s Job 资源限制：CPU/内存由 `ResourceLimits` 映射到 Pod `resources.limits`。

---

## 6. 安全验证

### 6.1 Docker 执行器

自动化测试：[test_docker_executor.py](../../tests/integration/sandbox/test_docker_executor.py)

| 检查 | 结果 |
|---|---|
| 非 root | `uid=65534`、`euid≠0` |
| 网络 | `--network none`，外网连接失败 |
| 只读 rootfs | `/engine`、`/` 写入被拒绝 |
| 输入只读 | `/input`、`/recipes` 写入被拒绝 |
| 输出可写 | `/output` 写入成功（产物目录） |
| capability | `CapEff=0`、`CapDrop=ALL` |
| 超时 | 2 s 超时后 SIGTERM→SIGKILL，`timed_out=true` |
| OOM | 64 MB 限制触发 OOM kill |
| 非零退出 | 退出码原样返回并分类为 failed |

### 6.2 K8s Pod 安全上下文

命令：[k8s-sandbox-isolation.sh](../../scripts/dev/k8s-sandbox-isolation.sh)

```text
uid 65534 euid 65534
network_internet=blocked:TimeoutError
network_service=reachable        # 主集群 kindnet 不执行 NetworkPolicy
engine_write=denied:OSError
root_write=denied:OSError
tmp_write=denied:OSError         # 探针未挂载 tmp emptyDir；真实 Job 会挂载
```

### 6.3 NetworkPolicy 实测（Calico）

主 kind 集群使用 kindnet，默认不执行 NetworkPolicy。为验证策略本身，另建临时集群 `hanson-calico`（禁用默认 CNI，安装 Calico v3.28.0），用“服务端 Pod + 客户端 Job”做 A/B 对比：

```text
[有 deny-all 策略] sandbox-net-client       policy_result=blocked:TimeoutError
[无策略基线]       sandbox-net-client-open  policy_result=reachable
```

说明：

- 策略对象：[sandbox.yaml](../../deploy/k8s/base/sandbox.yaml) 中的 `sandbox-job-deny-all`，选择 `app=hanson-sandbox-job`。
- 该对比证明在支持 NetworkPolicy 的 CNI 下，执行 Pod 的东西向流量被完全阻断。
- 主集群 kindnet 下该策略不生效，因此生产必须使用 Calico/Cilium 等支持策略的 CNI；该项已记入风险与后续。

复现脚本：[k8s-networkpolicy-check.sh](../../scripts/dev/k8s-networkpolicy-check.sh)、临时集群配置 [kind-calico.yaml](../../deploy/k8s/kind-calico.yaml)。

---

## 7. 结论与决策

1. **默认运行时：containerd + runc**。满足全部硬性隔离要求，兼容性与运维成本最低。
2. **可选加固：gVisor**。已通过 KVM 最小执行；节点安装 runsc 并注册 Docker/containerd runtime 后，通过 `SANDBOX_RUNTIME=runsc` 切换，执行契约不变。
3. **Kata：本期不选**。环境无法完成最小执行验证；若后续引入不可信第三方配方或需要 VM 级隔离，再在具备 KVM 的节点池用 kata-deploy 评估。
4. **CNI 要求**：生产必须使用支持 NetworkPolicy 的 CNI；kindnet 仅用于开发集群。
5. **决策记录**：已回填 [D-007](decision-log.md#d-007-沙箱运行时按多维度评估选择)。

---

## 8. 后续事项

| 事项 | 说明 |
|---|---|
| gVisor 节点注册 | 在节点 `/etc/docker/daemon.json` 或 containerd config 中注册 `runsc`，做一次 `docker run --runtime=runsc` 回归 |
| Kata 生产验证 | 独立 KVM 节点池 + kata-deploy；复测启动开销与 GPU/IO 兼容性 |
| K8s 大输入 | 当前 Job 执行器用 ConfigMap 传递工作区（≤800 KB）；大 OCR 输入后续改为 PVC/对象存储挂载 |
| 资源监控 | 增加 Pod/容器级 memory peak 采集，替换当前 `peak_memory_mb` 的 RSS 估算 |
