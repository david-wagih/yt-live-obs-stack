import asyncio
import logging
import os
import random

from fastapi import FastAPI, Response
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from telemetry import setup_telemetry

setup_telemetry()

logger = logging.getLogger("observability-demo-api")
tracer = trace.get_tracer("observability-demo-api")

app = FastAPI(title="Observability Demo API")
FastAPIInstrumentor.instrument_app(app)

SLOW_MIN_SECONDS = float(os.getenv("SLOW_MIN_SECONDS", "2"))
SLOW_MAX_SECONDS = float(os.getenv("SLOW_MAX_SECONDS", "5"))
ORDERS_FAIL_RATE = float(os.getenv("ORDERS_FAIL_RATE", "0"))
ORDERS_SLOW_RATE = float(os.getenv("ORDERS_SLOW_RATE", "0"))
ORDERS_SLOW_SECONDS = float(os.getenv("ORDERS_SLOW_SECONDS", "1.5"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    logger.info("root request handled")
    return {"message": "observability demo api"}


@app.get("/api/orders")
async def get_orders():
    with tracer.start_as_current_span("validate-request"):
        await asyncio.sleep(0.01)

    if random.random() < ORDERS_FAIL_RATE:
        logger.error("order request failed intentionally")
        return Response(status_code=500, content="order lookup failed")

    with tracer.start_as_current_span("query-orders-database"):
        delay = ORDERS_SLOW_SECONDS if random.random() < ORDERS_SLOW_RATE else 0.05
        await asyncio.sleep(delay)
        orders = [{"id": 1, "item": "keyboard"}, {"id": 2, "item": "monitor"}]

    with tracer.start_as_current_span("serialize-response"):
        await asyncio.sleep(0.01)

    logger.info("order request completed")
    return {"orders": orders}


@app.get("/slow")
async def slow():
    duration = random.uniform(SLOW_MIN_SECONDS, SLOW_MAX_SECONDS)
    logger.warning("slow operation triggered")
    with tracer.start_as_current_span("simulated-slow-operation"):
        await asyncio.sleep(duration)
    return {"message": "slow response", "duration_seconds": round(duration, 2)}


@app.get("/error")
async def error():
    logger.error("request failed intentionally")
    return Response(status_code=500, content="intentional error")
