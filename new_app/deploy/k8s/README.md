# K8s 部署（M0 占位）

M0 只提供命名空间与本地 WSL 验证说明；完整 Deployment/Service/HPA/NetworkPolicy 在 M1/M4 按服务逐步补齐。

## WSL 验证顺序

1. 在 WSL 内安装 k3s/kind/minikube 之一（M0 记录选型）。
2. `kubectl apply -f base/namespace.yaml`。
3. 后续里程碑补充服务清单后，再部署七个服务。
4. 验证 `kubectl get pods -n hanson-standard` 与 NetworkPolicy。

## 约束

- 沙箱节点与业务节点隔离。
- 网关是唯一公网入口。
- 本地开发/测试对象存储使用 MinIO。
- 模型操作在模型服务器执行，不在 K8s 业务集群内。
