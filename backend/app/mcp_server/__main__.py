import uvicorn

from app.mcp_server.server import build_app

if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=8020, log_level="info")  # noqa: S104 -- bound to loopback by compose
