"""SEC-17/18 fix lab probe. Usage: probe_fix.py fixtures|ufd|real <label> <host:port> [urls.json]

Prints TSV: label, case, status, content-type, bytes, detail. Signed query
strings and the lab token are redacted from every detail.
"""

import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN = "labtoken-not-a-real-secret"
FILES = "http://fix-files:8080"
CANARY = "http://fix-canary:8080"


def redact(s: str) -> str:
    s = re.sub(r"(\.(?:tif|TIF|tiff|json))\?[^'\" ]*", r"\1?<redacted>", s)
    return re.sub(r"(sig|access_token)=[^&'\" ]+", r"\1=<redacted>", s)


def get(base, path, params=None, token=True, host=None):
    q = list(params or [])
    if token:
        q.append(("access_token", TOKEN))
    url = f"http://{base}{path}" + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Host": host} if host else {})
    try:
        r = urllib.request.urlopen(req, timeout=90)
        return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()
    except Exception as e:  # noqa: BLE001 - lab harness: record any transport failure as a row
        return "ERR", "", repr(e).encode()


def row(label, case, res, extra=""):
    status, ctype, body = res
    if ctype.startswith("image/"):
        detail = f"magic={body[:4].hex()}"
    else:
        try:
            j = json.loads(body)
            detail = json.dumps(j.get("detail", j) if isinstance(j, dict) else j)
        except ValueError:
            detail = body[:200].decode("utf-8", "replace")
    detail = (f"{extra} | " if extra else "") + redact(detail)[:230]
    print(f"{label}\t{case}\t{status}\t{ctype.split(';')[0]}\t{len(body)}\t{detail}", flush=True)


def canary_hits():
    with urllib.request.urlopen(f"{CANARY}/_hits", timeout=10) as r:
        return json.load(r).get("/canary.tif", 0)


def info_driver(res):
    try:
        return json.loads(res[2]).get("driver")
    except (ValueError, AttributeError):
        return None


def fixtures(label, base):
    row(label, "healthz anonymous", get(base, "/healthz", token=False))
    row(label, "healthz with token", get(base, "/healthz"))
    r = get(base, "/cog/info", [("url", f"{FILES}/real.tif")])
    row(label, "real.tif info", r, f"driver={info_driver(r)}")
    row(label, "notallowed.png info", get(base, "/cog/info", [("url", f"{FILES}/notallowed.png")]))
    r = get(base, "/cog/info", [("url", f"{FILES}/nc4.tif")])
    row(label, "nc4.tif (HDF5 bytes) info", r, f"driver={info_driver(r)}")
    r = get(base, "/cog/info", [("url", f"{FILES}/nc_classic.tif")])
    row(label, "nc_classic.tif info", r, f"driver={info_driver(r)}")
    before = canary_hits()
    r = get(base, "/cog/info", [("url", f"{FILES}/vrt_ssrf.tif")])
    row(label, "vrt_ssrf.tif info", r, f"driver={info_driver(r)} canary_hits+={canary_hits() - before}")
    before = canary_hits()
    r = get(base, "/cog/statistics", [("url", f"{FILES}/vrt_ssrf.tif")])
    row(label, "vrt_ssrf.tif statistics", r, f"canary_hits+={canary_hits() - before}")
    before = canary_hits()
    r = get(base, "/cog/info", [("url", f"{FILES}/vrt_ssrf_noext.tif")])
    row(label, "vrt_ssrf_noext.tif info", r, f"canary_hits+={canary_hits() - before}")
    row(label, "vrt_raw_environ.tif statistics", get(base, "/cog/statistics", [("url", f"{FILES}/vrt_raw_environ.tif")]))
    # b1<<1 and "b1 is b1" were added after the scored run showed numexpr
    # 2.14.1 already rejects int()/len(); they were not predicted.
    for expr in ("b1*2", "where(b1>0,1,0)", "b1*0+int(True)", "b1*0+len('ab')", "b1.__class__", "b1<<1", "b1 is b1"):
        res = get(base, "/cog/statistics", [("url", f"{FILES}/real.tif"), ("expression", expr)])
        row(label, f"expression {expr}", res)
    host = "lab/badhost-probe?x="
    res = get(base, "/tileMatrixSets", host=host)
    reflected = b"/badhost-probe/" in res[2]
    row(label, f"BadHost Host={host!r} /tileMatrixSets", (res[0], "text/x-summary", b""), f"reflected={reflected}")
    row(label, "/mosaicjson/info", get(base, "/mosaicjson/info", [("url", f"{FILES}/x.json")]))
    row(label, "/zarr/info", get(base, "/zarr/info", [("url", f"{FILES}/real.tif")]))


def ufd(label, base):
    for name in ("nc_classic", "nc4"):
        r = get(base, "/cog/info", [("url", f"{FILES}/{name}.tif")])
        row(label, f"{name}.tif info (userfaultfd available)", r, f"driver={info_driver(r)}")


def tile(lon, lat, z):
    n = 2**z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return f"{z}/{x}/{y}"


RGB = [("bidx", "1"), ("bidx", "2"), ("bidx", "3"), ("rescale", "0,255")]


def real(label, base, urls):
    cog = "/cog/tiles/WebMercatorQuad"
    row(label, "naip /cog/tiles z16", get(base, f"{cog}/{tile(-104.9687, 39.7187, 16)}", [("url", urls["naip"]), *RGB]))
    row(label, "sentinel2 /cog/tiles z13", get(base, f"{cog}/{tile(-104.99, 39.74, 13)}", [("url", urls["sentinel2"]), *RGB]))
    row(label, "usgs_topo /cog/tiles z13", get(base, f"{cog}/{tile(-104.9, 39.74, 13)}", [("url", urls["usgs_topo"]), *RGB]))
    landsat = [
        ("url", urls["landsat_item"]),
        *[("assets", a) for a in ("red", "green", "blue")],
        ("nodata", "0"),
        *[("rescale", "7000,14000")] * 3,
    ]
    row(label, "landsat /stac/tiles .png z12", get(base, f"/stac/tiles/WebMercatorQuad/{tile(-104.99, 39.74, 12)}.png", landsat))
    bbox = "-104.975,39.712,-104.962,39.725"
    row(label, "naip /cog/bbox .png (preview)", get(base, f"/cog/bbox/{bbox}/512x512.png", [("url", urls["naip"]), *RGB]))
    r = get(base, "/cog/info", [("url", urls["usgs_topo"])])
    row(label, "usgs_topo /cog/info (warmup)", r, f"driver={info_driver(r)}")
    r = get(base, "/stac/info", [("url", urls["landsat_item"]), *[("assets", a) for a in ("red", "green", "blue")]])
    row(label, "landsat /stac/info (warmup)", r)


if __name__ == "__main__":
    mode, label, base = sys.argv[1:4]
    if mode == "fixtures":
        fixtures(label, base)
    elif mode == "ufd":
        ufd(label, base)
    else:
        real(label, base, json.load(open(sys.argv[4])))
