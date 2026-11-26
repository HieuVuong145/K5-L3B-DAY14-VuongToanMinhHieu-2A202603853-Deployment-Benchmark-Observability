"""
Production AI Agent — Part 6 Final Project
"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
logger = logging.getLogger(__name__)

_is_shutting_down = False
_in_flight = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _is_shutting_down
    logger.info(json.dumps({"event": "startup", "status": "ready"}))
    yield
    _is_shutting_down = True
    logger.info(json.dumps({"event": "shutdown", "in_flight": _in_flight}))
    waited = 0.0
    while _in_flight > 0 and waited < 5.0:
        await asyncio.sleep(0.1)
        waited += 0.1
    logger.info(json.dumps({"event": "shutdown_complete"}))


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def track_requests(request: Request, call_next):
    global _in_flight
    _in_flight += 1
    start = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            json.dumps({
                "event": "request",
                "path": request.url.path,
                "status": response.status_code,
                "ms": elapsed_ms,
            })
        )
        return response
    finally:
        _in_flight -= 1


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str = Field(default="default", min_length=1, max_length=100)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn chạy."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness probe: 200 khi sẵn sàng, 503 khi shutdown hoặc mất Redis."""
    if _is_shutting_down or not redis_healthy():
        raise HTTPException(status_code=503, detail="Agent not ready")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost = record_cost(input_tokens, output_tokens)

    return {
        "question": body.question,
        "answer": answer,
        "cost_usd": cost,
    }
