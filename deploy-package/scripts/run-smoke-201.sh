set -u
cd /home/htjiance8/hanson-deploy/deploy-package
chmod +x scripts/*.sh models/*.sh 2>/dev/null || true
bash scripts/smoke-test.sh --cleanup
