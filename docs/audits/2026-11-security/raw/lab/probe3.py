exec(open("/scripts/probe.py").read().split('F="http')[0])
F="http://audit-files:8080"; O="audit-titiler-open"
for e in ["b1*2", "b1.__class__", "b1*0+sum(c for c in [])", "where(b1>0,1,0)"]:
    get(O,"/cog/statistics",url=f"{F}/real.tif",expression=e)
