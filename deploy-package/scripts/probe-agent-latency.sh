set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== agent recent logs =="
docker compose logs --tail 120 agent 2>&1 | grep -iE 'endpoint|failover|duration|elapsed|chat|error|timeout' | tail -25
echo "== orchestration stage logs =="
docker compose logs --tail 400 orchestration 2>&1 | grep -iE 'routing|review|agent|duration|elapsed' | tail -25
echo "== reachability of agent endpoints from app net =="
docker compose exec -T agent python -c "
import socket
for host,port in [('39.107.239.208',35035),('193.168.2.201',9991),('193.168.2.202',9988)]:
    s=socket.socket(); s.settimeout(4)
    try:
        s.connect((host,port)); print(host,port,'open')
    except Exception as e: print(host,port,'FAIL',e)
    finally: s.close()
"
