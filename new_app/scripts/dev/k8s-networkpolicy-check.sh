#!/usr/bin/env bash
# Compare sandbox Job connectivity with and without the deny-all NetworkPolicy.
# Requires a policy-capable CNI (Calico).
set -euo pipefail

CONTEXT="${CONTEXT:-kind-hanson-calico}"
NAMESPACE="${NAMESPACE:-default}"
export PATH="$PATH:$HOME/.local/bin"
KUBECTL=(kubectl --context "$CONTEXT" -n "$NAMESPACE")

cleanup() {
  "${KUBECTL[@]}" delete job sandbox-net-client sandbox-net-client-open --ignore-not-found >/dev/null 2>&1 || true
  "${KUBECTL[@]}" delete pod sandbox-net-server --ignore-not-found >/dev/null 2>&1 || true
  "${KUBECTL[@]}" delete networkpolicy sandbox-job-deny-all --ignore-not-found >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup

echo "[1/5] 启动服务端 Pod"
"${KUBECTL[@]}" apply -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: sandbox-net-server
  labels:
    app: sandbox-net-server
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 65534
    runAsGroup: 65534
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: server
      image: hanson-sandbox-runtime:local
      imagePullPolicy: IfNotPresent
      command: ["python", "-m", "http.server", "8080"]
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
YAML

"${KUBECTL[@]}" wait --for=condition=Ready pod/sandbox-net-server --timeout=60s
SERVER_IP="$("${KUBECTL[@]}" get pod sandbox-net-server -o jsonpath='{.status.podIP}')"
echo "  server_ip=$SERVER_IP"

run_client() {
  local name="$1"
  "${KUBECTL[@]}" apply -f - <<YAML
apiVersion: batch/v1
kind: Job
metadata:
  name: $name
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 60
  template:
    metadata:
      labels:
        app: hanson-sandbox-job
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: probe
          image: hanson-sandbox-runtime:local
          imagePullPolicy: IfNotPresent
          env:
            - name: PROBE_TARGET
              value: "$SERVER_IP"
          command:
            - python
            - -c
            - |
              import os, socket
              target = os.environ["PROBE_TARGET"]
              try:
                  socket.create_connection((target, 8080), 3).close()
                  print("policy_result=reachable")
              except OSError as exc:
                  print("policy_result=blocked:" + type(exc).__name__)
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
YAML
  "${KUBECTL[@]}" wait --for=condition=complete "job/$name" --timeout=90s || true
  echo "--- $name ---"
  "${KUBECTL[@]}" logs "job/$name" || true
}

echo "[2/5] 应用 deny-all NetworkPolicy"
"${KUBECTL[@]}" apply -f - <<'YAML'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-job-deny-all
spec:
  podSelector:
    matchLabels:
      app: hanson-sandbox-job
  policyTypes:
    - Ingress
    - Egress
YAML

echo "[3/5] 受策略限制的客户端"
run_client sandbox-net-client

echo "[4/5] 移除策略后的基线"
"${KUBECTL[@]}" delete networkpolicy sandbox-job-deny-all --ignore-not-found >/dev/null
run_client sandbox-net-client-open

echo "[5/5] 清理"
