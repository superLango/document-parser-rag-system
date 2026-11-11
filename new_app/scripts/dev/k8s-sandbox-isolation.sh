#!/usr/bin/env bash
# Verify the sandbox Job isolation surface in K8s (securityContext + NetworkPolicy).
# Usage:
#   bash k8s-sandbox-isolation.sh                          # main kind cluster
#   CONTEXT=kind-hanson-calico NAMESPACE=default bash ...  # policy-capable test cluster
set -euo pipefail

NAMESPACE="${NAMESPACE:-hanson-standard}"
JOB="sandbox-net-probe"
KUBECTL=(kubectl)
if [ -n "${CONTEXT:-}" ]; then
  KUBECTL+=(--context "$CONTEXT")
fi
export PATH="$PATH:$HOME/.local/bin"

"${KUBECTL[@]}" -n "$NAMESPACE" delete job "$JOB" --ignore-not-found >/dev/null

"${KUBECTL[@]}" apply -f - <<YAML
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: sandbox-job-deny-all
  namespace: $NAMESPACE
spec:
  podSelector:
    matchLabels:
      app: hanson-sandbox-job
  policyTypes:
    - Ingress
    - Egress
---
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB
  namespace: $NAMESPACE
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
          command:
            - python
            - -c
            - |
              import os, socket
              print("uid", os.getuid(), "euid", os.geteuid())
              for name, target in (("internet", ("1.1.1.1", 80)), ("api", ("10.96.0.1", 443))):
                  try:
                      socket.create_connection(target, 3).close()
                      print(f"network_{name}=reachable")
                  except OSError as exc:
                      print(f"network_{name}=blocked:{type(exc).__name__}")
              for name, path in (("engine_write", "/engine/evil"), ("root_write", "/evil"), ("tmp_write", "/tmp/evil")):
                  try:
                      open(path, "w").write("x")
                      print(f"{name}=allowed")
                  except OSError as exc:
                      print(f"{name}=denied:{type(exc).__name__}")
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
YAML

"${KUBECTL[@]}" -n "$NAMESPACE" wait --for=condition=complete "job/$JOB" --timeout=90s || true
echo "--- probe logs ---"
"${KUBECTL[@]}" -n "$NAMESPACE" logs "job/$JOB" || true
"${KUBECTL[@]}" -n "$NAMESPACE" delete job "$JOB" --ignore-not-found >/dev/null
