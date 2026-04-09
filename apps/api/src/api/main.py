from fastapi import FastAPI

app = FastAPI(title="TraceAgent API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api", "version": app.version}


@app.get("/health/ready")
def readiness() -> dict[str, str]:
    return {"status": "ok", "service": "api", "checks": "pending"}
