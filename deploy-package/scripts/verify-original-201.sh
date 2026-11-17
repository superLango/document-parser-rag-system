set -u
cd /home/htjiance8/hanson-deploy/deploy-package
GW=http://127.0.0.1:18001
WEB=http://127.0.0.1:18081
RESP=$(curl -sS -m 120 -X POST "$GW/api/v1/integration/upload?kb_id=$(python3 -c 'import uuid;print(uuid.uuid4())')&prompt_id=$(python3 -c 'import uuid;print(uuid.uuid4())')" -F "file=@samples/smoke.pdf;type=application/pdf")
DOC=$(printf '%s' "$RESP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["data"]["document_id"])')
echo "document_id=$DOC"
echo "== original file via web =="
curl -sS -m 20 -o /tmp/orig.pdf -D /tmp/orig.hdr -w 'http=%{http_code} type=%{content_type} bytes=%{size_download}\n' "$WEB/v1/documents/$DOC/file"
head -c 8 /tmp/orig.pdf | od -c | head -1
grep -i 'content-disposition' /tmp/orig.hdr | head -1
echo "== cleanup =="
curl -sS -o /dev/null -w 'delete=%{http_code}\n' -X DELETE "$GW/v1/documents/$DOC"
rm -f /tmp/orig.pdf /tmp/orig.hdr
