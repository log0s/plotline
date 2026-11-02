#!/usr/bin/env bash
# SEC-17/18 fix lab. Usage: run_lab.sh <dir holding urls.json and items/>
# Fixture instances sit on an --internal network with no route out; the
# real-source instances sit on a plain bridge so GDAL can reach PC and TNM.
set -euo pipefail
cd "$(dirname "$0")"
REAL=$1
LAB=$PWD
WWW=$(cd ../lab/www && pwd)
OLD=ghcr.io/developmentseed/titiler:1.2.1
NEW=ghcr.io/developmentseed/titiler@sha256:5b739117ff60d3cef9b0e0b8d9f4d628032c00a4965117e3f745cadc79fa7287
TOK=labtoken-not-a-real-secret
NAMES="fix-files fix-canary fix-items fx-before fx-after fx-nofix fx-before-ufd fx-after-ufd fx-nofix-ufd fx-real-before fx-real-after"

cleanup() { docker rm -f $NAMES >/dev/null 2>&1 || true; docker network rm fixlab fixlab-egress >/dev/null 2>&1 || true; }
cleanup
trap cleanup EXIT
docker network create --internal fixlab >/dev/null
docker network create fixlab-egress >/dev/null

serve() { # name network dir [extra docker args]
  local name=$1 net=$2 dir=$3; shift 3
  docker run -d --name "$name" --network "$net" "$@" -v "$LAB/canary_server.py:/srv.py:ro" -v "$dir:/www:ro" \
    --entrypoint python "$NEW" -I /srv.py /www >/dev/null
}
serve fix-files fixlab "$WWW"
# vrt_ssrf.tif (the audit's fixture) names http://audit-canary:8080/canary.tif.
serve fix-canary fixlab "$WWW" --network-alias audit-canary
serve fix-items fixlab-egress "$REAL/items"

titiler() { # name image envfile network [extra docker args]
  local name=$1 image=$2 envfile=$3 net=$4; shift 4
  docker run -d --name "$name" --network "$net" --env-file "$envfile" \
    -e TITILER_API_GLOBAL_ACCESS_TOKEN=$TOK "$@" "$image" >/dev/null
}
titiler fx-before "$OLD" ../lab/fly-titiler.env fixlab
titiler fx-after "$NEW" fly-titiler-2.4.0.env fixlab
titiler fx-nofix "$NEW" fly-titiler-2.4.0-noskip.env fixlab
titiler fx-before-ufd "$OLD" ../lab/fly-titiler.env fixlab --security-opt seccomp=unconfined
titiler fx-after-ufd "$NEW" fly-titiler-2.4.0.env fixlab --security-opt seccomp=unconfined
titiler fx-nofix-ufd "$NEW" fly-titiler-2.4.0-noskip.env fixlab --security-opt seccomp=unconfined
titiler fx-real-before "$OLD" ../lab/fly-titiler.env fixlab-egress
titiler fx-real-after "$NEW" fly-titiler-2.4.0.env fixlab-egress

# The probe container needs both networks: start it on fixlab, connect egress.
probe_both() {
  local cid
  cid=$(docker create --network fixlab -v "$LAB/probe_fix.py:/p.py:ro" -v "$REAL/urls.json:/urls.json:ro" \
    --entrypoint python "$NEW" -I /p.py "$@")
  docker network connect fixlab-egress "$cid"
  docker start -a "$cid"
  docker rm "$cid" >/dev/null
}

wait_up() { # name port
  for _ in $(seq 60); do
    if docker exec "$1" curl -sf -m 5 "http://localhost:$2/healthz?access_token=$TOK" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "$1 never became healthy" >&2; docker logs "$1" 2>&1 | tail -20 >&2; return 1
}
for n in fx-before fx-before-ufd fx-real-before; do wait_up $n 80; done
for n in fx-after fx-nofix fx-after-ufd fx-nofix-ufd fx-real-after; do wait_up $n 8000; done

{
  echo "== images"
  for n in fx-before fx-after; do
    echo "-- $n: $(docker inspect -f '{{.Config.Image}}' $n) image-id $(docker inspect -f '{{.Image}}' $n | cut -c1-19)"
    docker exec $n sh -c 'echo "uid=$(id -u)"; python -c "
import os, sys, starlette, rio_tiler, rasterio, fastapi, numexpr, certifi
print(\"python\", sys.version.split()[0]); print(\"starlette\", starlette.__version__); print(\"fastapi\", fastapi.__version__)
print(\"rio-tiler\", rio_tiler.__version__); print(\"rasterio\", rasterio.__version__, \"GDAL\", rasterio.__gdal_version__)
print(\"numexpr\", numexpr.__version__); print(\"certifi\", certifi.__version__)
skip = os.environ.get(\"GDAL_SKIP\")
print(\"GDAL_SKIP entries\", len(skip.split(\",\")) if skip else 0)
with rasterio.Env() as e: d = sorted(e.drivers())
print(\"drivers registered\", len(d), d if len(d) < 20 else \"(all)\")
"' 2>/dev/null
  done
} > versions.txt

{
  printf 'instance\tcase\tstatus\tcontent-type\tbytes\tdetail\n'
  for pair in "before fx-before:80" "after fx-after:8000" "nofix fx-nofix:8000"; do
    set -- $pair; probe_both fixtures "$1" "$2"
  done
  for pair in "before-ufd fx-before-ufd:80" "after-ufd fx-after-ufd:8000" "nofix-ufd fx-nofix-ufd:8000"; do
    set -- $pair; probe_both ufd "$1" "$2"
  done
} > fixtures-out.tsv

{
  printf 'instance\tcase\tstatus\tcontent-type\tbytes\tdetail\n'
  probe_both real before fx-real-before:80 /urls.json
  probe_both real after fx-real-after:8000 /urls.json
} > real-out.tsv

# Server-side errors, for any 500 the tables show (token never printed: it is a lab value).
for n in fx-after fx-real-after; do echo "== $n"; docker logs "$n" 2>&1 | grep -iE "error|exception" | tail -15 | sed -E 's/((sig|access_token)=)[^&"\x27 ]+/\1<redacted>/g' || true; done > server-errors.txt
echo done
