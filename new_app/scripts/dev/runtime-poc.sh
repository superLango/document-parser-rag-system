#!/usr/bin/env bash
# Runtime PoC for M4: runc (baseline), gVisor and Kata capability probes.
# Run inside WSL/Linux as root for the gVisor section:
#   wsl -u root -e bash /mnt/f/.../new_app/scripts/dev/runtime-poc.sh
set -uo pipefail

export PATH="$PATH:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

echo "== runc (docker, isolate flags) =="
docker run --rm --runtime=runc --network none --read-only --user 65534:65534 \
  --cap-drop ALL --security-opt no-new-privileges --memory 128m --cpus 0.5 \
  --pids-limit 64 --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --entrypoint sh hanson-sandbox-runtime:local -c '
    echo uid=$(id -u)
    echo cap_eff=$(grep CapEff /proc/self/status | awk "{print \$2}")
    (echo x > /engine/probe && echo engine_write=allowed) || echo engine_write=denied
    (echo x > /tmp/probe && echo tmp_write=allowed) || echo tmp_write=denied
    (python -c "import socket; socket.create_connection((\"1.1.1.1\",80),2)" 2>/dev/null \
      && echo network=open) || echo network=blocked
  '
echo "runc_exit=$?"

echo
echo "== gVisor =="
if command -v runsc >/dev/null 2>&1; then
  runsc --version
  runsc --network=none --platform=kvm do sh -c '
    echo uid=$(id -u)
    (python3 -c "import socket; socket.create_connection((\"1.1.1.1\",80),2)" 2>/dev/null \
      && echo network=open) || echo network=blocked
    (echo x > /tmp/gvisor-probe && echo tmp_write=allowed) || echo tmp_write=denied
  '
  echo "gvisor_exit=$?"
  echo "gvisor_nonroot_uid=$(runsc --network=none --platform=kvm do su nobody -s /bin/sh -c 'id -u')"
else
  echo "runsc=not_installed"
fi

echo
echo "== Kata =="
if command -v kata-runtime >/dev/null 2>&1; then
  kata-runtime --version
  kata-runtime check || true
else
  echo "kata-runtime=not_installed"
  apt-cache policy kata-containers 2>/dev/null | awk '/Candidate/ {print "apt_candidate=" $2}'
  command -v qemu-system-x86_64 >/dev/null 2>&1 && echo qemu=present || echo qemu=missing
fi
