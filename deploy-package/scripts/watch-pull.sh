for i in 1 2 3 4; do
  printf '%s size=' "$(date +%T)"
  du -sm /var/lib/docker 2>/dev/null | awk '{print $1" MB"}'
  tail -2 /tmp/pull_py.log | tr '\r' '\n' | tail -2
  sleep 20
done
