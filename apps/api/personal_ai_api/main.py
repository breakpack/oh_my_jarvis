from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from personal_ai_api import __version__
from personal_ai_api.chat import router as chat_router
from personal_ai_api.config import settings
from personal_ai_api.documents import router as documents_router
from personal_ai_api.knowledge import router as knowledge_router
from personal_ai_api.memory import router as memory_router
from personal_ai_api.projects import router as projects_router
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
app.include_router(chat_router)
app.include_router(projects_router)
app.include_router(memory_router)
app.include_router(documents_router)
app.include_router(knowledge_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
