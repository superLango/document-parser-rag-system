from fastapi import FastAPI

SERVICE_VERSION = "0.0.0"


def create_app(service_name: str, version: str = SERVICE_VERSION) -> FastAPI:
    app = FastAPI(title=f"Hanson {service_name}", version=version)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service_name, "version": version}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready", "service": service_name, "version": version}

    return app
