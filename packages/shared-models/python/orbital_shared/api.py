from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from orbital_semconv import configure_telemetry


def create_service(title: str, service_name: str) -> FastAPI:
    configure_telemetry(service_name)
    app = FastAPI(title=title, version="0.1.0", docs_url="/docs")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    FastAPIInstrumentor.instrument_app(app)
    return app
