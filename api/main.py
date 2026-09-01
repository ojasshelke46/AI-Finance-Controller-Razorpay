import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lib import db
from lib.byteplus import ByteplusError, complete_text
from lib.razorpay_client import RazorpayError
from lib.razorpay_client import ping as razorpay_ping
from routes.console import router as console_router
from routes.qna import router as qna_router
from runtime import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the background scheduler with the API and stop it with the
    API, so the autonomous side has exactly the same lifetime as the
    process serving requests."""
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="AI Finance Controller API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(qna_router)
app.include_router(console_router)


def _check_supabase() -> dict:
    start = time.monotonic()
    try:
        db.run_with_retry(lambda: db.get_client().table("run_state").select("id").limit(1).execute())
        return {"status": "up", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "down", "latency_ms": round((time.monotonic() - start) * 1000, 1), "error": str(exc)}


def _check_byteplus() -> dict:
    start = time.monotonic()
    try:
        complete_text("You are a health check.", "Reply with the single word: pong")
        return {"status": "up", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except ByteplusError as exc:
        return {"status": "down", "latency_ms": round((time.monotonic() - start) * 1000, 1), "error": str(exc)}


def _check_razorpay() -> dict:
    start = time.monotonic()
    try:
        razorpay_ping()
        return {"status": "up", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except RazorpayError as exc:
        return {"status": "down", "latency_ms": round((time.monotonic() - start) * 1000, 1), "error": str(exc)}


@app.get("/health")
def health():
    checks = {
        "supabase": _check_supabase(),
        "byteplus": _check_byteplus(),
        "razorpay": _check_razorpay(),
    }
    overall = "ok" if all(c["status"] == "up" for c in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}
