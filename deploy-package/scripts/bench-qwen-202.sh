set -u
cd /home/htjiance8/hanson-deploy/deploy-package
docker compose exec -T agent python - <<'PY'
import json, time, urllib.request

def call(max_tokens, prompt, tag):
    body = json.dumps({
        "model": "Qwen3.6-35B-A3B-FP8",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request("http://193.168.2.202:9988/v1/chat/completions", data=body,
                                 headers={"content-type": "application/json"})
    t = time.monotonic()
    r = json.loads(urllib.request.urlopen(req, timeout=300).read())
    dt = time.monotonic() - t
    u = r.get("usage") or {}
    ct = u.get("completion_tokens") or 0
    print("%s max_tokens=%d elapsed=%.1fs completion=%d prompt=%d speed=%.1f tok/s" % (
        tag, max_tokens, dt, ct, u.get("prompt_tokens") or 0, (ct / dt if dt else 0)))

call(16, "只回复 JSON: {\"ok\": true}", "tiny")
call(128, "用一句话说明什么是抗拉强度。", "short")
call(512, "列出10条钢材力学性能检测项目，每条一行。", "medium")
PY
