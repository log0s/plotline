import sys; sys.path.insert(0,"/scripts")
exec(open("/scripts/probe.py").read().split('F="http')[0])
F="http://audit-files:8080"; O="audit-titiler-open"; U="audit-titiler-ufd"
get(U,"/healthz")
for n in ("nc_classic","nc4"):
    get(U,"/cog/info",url=f"{F}/{n}.tif")
get(O,"/cog/statistics",url=f"{F}/vrt_ssrf_noext.tif")
