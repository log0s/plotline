import starlette
from starlette.requests import Request
for host in ["localhost", "localhost/api/v1/health?x=", "evil.example/admin#", "a@b"]:
    scope = {"type": "http", "method": "GET", "path": "/cog/tiles/1/2/3", "raw_path": b"/cog/tiles/1/2/3",
             "query_string": b"url=x", "headers": [(b"host", host.encode())], "scheme": "http", "server": ("127.0.0.1", 80), "root_path": ""}
    r = Request(scope)
    print(f"starlette {starlette.__version__} host={host!r:32} scope.path=/cog/tiles/1/2/3 url.path={r.url.path!r} url={str(r.url)!r}")
