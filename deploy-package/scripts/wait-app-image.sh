old=526eab52d2b6
for i in $(seq 1 20); do
  cur=$(docker images -q hanson-new-app:local)
  printf '%s %s\n' "$(date +%T)" "$cur"
  if [ "$cur" != "$old" ]; then echo CHANGED; break; fi
  sleep 25
done
ps aux | grep -c '[q]emu-aarch64 pip' || true
