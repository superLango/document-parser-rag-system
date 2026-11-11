#!/usr/bin/env bash
# Rough warm-start benchmark: runc container vs gVisor sandbox (`runsc do`).
set -uo pipefail

run_runc() {
  local start end
  start="$(date +%s%N)"
  docker run --rm --runtime=runc --network none --read-only --user 65534:65534 \
    --cap-drop ALL --security-opt no-new-privileges \
    --entrypoint true hanson-sandbox-runtime:local
  end="$(date +%s%N)"
  echo "runc $(( (end - start) / 1000000 )) ms"
}

run_gvisor() {
  local start end
  start="$(date +%s%N)"
  runsc --network=none --platform=kvm do true
  end="$(date +%s%N)"
  echo "gvisor $(( (end - start) / 1000000 )) ms"
}

for _ in 1 2 3; do run_runc; done
for _ in 1 2 3; do run_gvisor; done
