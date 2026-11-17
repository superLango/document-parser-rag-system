set -u
D=/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker
echo "== files =="
ls -1 "$D"
echo "== project labels =="
for c in $(docker ps --format '{{.Names}}' | grep '^hanson-doc-parse'); do
  docker inspect "$c" --format '{{.Name}} project={{index .Config.Labels "com.docker.compose.project"}} file={{index .Config.Labels "com.docker.compose.project.config_files"}}'
done
echo "== ai01 compose head =="
grep -nE '^name:|container_name|ports|image' "$D/compose.ai01.yaml" | head -25
