from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from personal_ai_api import __version__
from personal_ai_api.config import settings
from personal_ai_api.telemetry import setup_telemetry

app = FastAPI(title="Personal AI OS - Assistant API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_telemetry(app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
