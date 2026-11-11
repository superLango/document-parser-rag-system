#!/usr/bin/env bash
LOG=/tmp/k8s-bootstrap.log

for _ in $(seq 1 10); do
  if grep -q '\[k8s\] DONE' "$LOG" 2>/dev/null; then
    echo "K8S_DONE"
    grep '\[k8s\]' "$LOG" | tail -n 12
    exit 0
  fi
  if ! pgrep -f 'k8s-bootstrap.sh' >/dev/null; then
    echo "K8S_SCRIPT_EXITED"
    grep -E '\[k8s\]|error|Error|failed' "$LOG" | tail -n 20
    exit 1
  fi
  size=$(stat -c %s "$HOME/.local/bin/kubectl" 2>/dev/null || echo 0)
  echo "$(date +%H:%M:%S) kubectl_bytes=${size}"
  sleep 60
done

echo "K8S_WAIT_TIMEOUT"
exit 2
