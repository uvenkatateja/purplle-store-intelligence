"""FastAPI main application for Store Intelligence API."""

import uuid
import time
import structlog
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.models import (
    init_db, get_db,
    IngestRequest, IngestResponse,
    MetricsResponse, FunnelResponse, HeatmapResponse,
    AnomaliesResponse, HealthResponse, HeatmapZone
)
from app.ingestion import EventIngestionService
from app.metrics import MetricsService
from app.funnel import FunnelService
from app.anomalies import AnomalyDetectionService
from app.health import HealthService

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    # Startup
    logger.info("application_starting")
    from app import models as _m
    _m.Base.metadata.create_all(bind=_m.engine)
    logger.info("database_initialized")
    yield
    # Shutdown
    logger.info("application_shutting_down")


app = FastAPI(
    title="Store Intelligence API",
    description="Production-ready CCTV analytics system for retail stores",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Structured logging middleware for all requests."""
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    
    start_time = time.time()
    
    # Log request
    logger.info(
        "request_started",
        trace_id=trace_id,
        method=request.method,
        path=request.url.path,
        client_host=request.client.host if request.client else None
    )
    
    try:
        response = await call_next(request)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Log response
        logger.info(
            "request_completed",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            latency_ms=round(latency_ms, 2)
        )
        
        # Add trace_id to response headers
        response.headers["X-Trace-ID"] = trace_id
        
        return response
        
    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        
        logger.error(
            "request_failed",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            error=str(e),
            latency_ms=round(latency_ms, 2)
        )
        
        raise


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for graceful degradation."""
    trace_id = getattr(request.state, 'trace_id', 'unknown')
    
    logger.error(
        "unhandled_exception",
        trace_id=trace_id,
        error=str(exc),
        error_type=type(exc).__name__
    )
    
    # Check if it's a database error
    if "database" in str(exc).lower() or "connection" in str(exc).lower():
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "service_unavailable",
                "message": "Database service is temporarily unavailable",
                "trace_id": trace_id
            }
        )
    
    # Generic error response (no stack traces)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "trace_id": trace_id
        }
    )


@app.post("/events/ingest", response_model=IngestResponse)
async def ingest_events(
    request: Request,
    ingest_request: IngestRequest,
    db: Session = Depends(get_db)
):
    """
    Ingest a batch of events (up to 500).
    
    - Idempotent by event_id
    - Partial success on malformed events
    - Structured error responses
    """
    trace_id = request.state.trace_id
    event_count = len(ingest_request.events)
    
    logger.info(
        "ingestion_started",
        trace_id=trace_id,
        event_count=event_count
    )
    
    if event_count > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch size exceeds maximum of 500 events"
        )
    
    try:
        ingestion_service = EventIngestionService(db)
        success_count, failed_count, errors = ingestion_service.ingest_events(
            ingest_request.events,
            trace_id
        )
        
        logger.info(
            "ingestion_completed",
            trace_id=trace_id,
            success_count=success_count,
            failed_count=failed_count
        )
        
        return IngestResponse(
            success=failed_count == 0,
            ingested_count=success_count,
            failed_count=failed_count,
            errors=errors
        )
        
    except Exception as e:
        logger.error(
            "ingestion_error",
            trace_id=trace_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {str(e)}"
        )


@app.get("/stores/{store_id}/metrics", response_model=MetricsResponse)
async def get_store_metrics(
    store_id: str,
    date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get real-time metrics for a store.
    
    - Unique visitors (excluding staff)
    - Conversion rate
    - Average dwell per zone
    - Queue depth
    - Abandonment rate
    """
    try:
        metrics_service = MetricsService(db)
        
        # Parse date if provided
        target_date = datetime.fromisoformat(date).date() if date else None
        
        metrics = metrics_service.get_store_metrics(store_id, target_date)
        
        return MetricsResponse(**metrics)
        
    except Exception as e:
        logger.error(
            "metrics_error",
            store_id=store_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute metrics: {str(e)}"
        )


@app.get("/stores/{store_id}/funnel", response_model=FunnelResponse)
async def get_conversion_funnel(
    store_id: str,
    date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get conversion funnel for a store.
    
    Stages: Entry → Zone Visit → Billing Zone → Purchase
    
    - Session-based (no double counting)
    - Re-entries handled correctly
    """
    try:
        funnel_service = FunnelService(db)
        
        # Parse date
        target_date = datetime.fromisoformat(date).date() if date else datetime.utcnow().date()
        
        funnel = funnel_service.get_conversion_funnel(store_id, target_date)
        
        return FunnelResponse(
            store_id=store_id,
            date=str(target_date),
            funnel=funnel
        )
        
    except Exception as e:
        logger.error(
            "funnel_error",
            store_id=store_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compute funnel: {str(e)}"
        )


@app.get("/stores/{store_id}/heatmap", response_model=HeatmapResponse)
async def get_zone_heatmap(
    store_id: str,
    date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Get zone heatmap data.
    
    - Visit frequency per zone
    - Average dwell time
    - Normalized scores (0-100)
    - Data confidence flag
    """
    try:
        metrics_service = MetricsService(db)
        
        target_date = datetime.fromisoformat(date).date() if date else datetime.utcnow().date()
        start_time = datetime.combine(target_date, datetime.min.time())
        end_time = datetime.combine(target_date, datetime.max.time())
        
        # Get zone visit counts
        zone_visits = metrics_service.get_zone_visit_counts(store_id, start_time, end_time)
        
        # Get average dwell per zone
        avg_dwell = metrics_service._get_avg_dwell_per_zone(store_id, start_time, end_time)
        
        # Normalize scores
        max_visits = max(zone_visits.values()) if zone_visits else 1
        
        zones = []
        for zone_id in ['SKINCARE', 'MAKEUP', 'HAIRCARE', 'BODYCARE', 'BILLING']:
            visit_count = zone_visits.get(zone_id, 0)
            dwell_ms = avg_dwell.get(zone_id, 0.0)
            normalized = int((visit_count / max_visits) * 100) if max_visits > 0 else 0
            
            zones.append(HeatmapZone(
                zone_id=zone_id,
                visit_frequency=visit_count,
                avg_dwell_ms=dwell_ms,
                normalized_score=normalized
            ))
        
        # Determine data confidence
        total_sessions = sum(zone_visits.values())
        confidence = "HIGH" if total_sessions >= 20 else "LOW"
        
        return HeatmapResponse(
            store_id=store_id,
            date=str(target_date),
            zones=zones,
            data_confidence=confidence
        )
        
    except Exception as e:
        logger.error(
            "heatmap_error",
            store_id=store_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate heatmap: {str(e)}"
        )


@app.get("/stores/{store_id}/anomalies", response_model=AnomaliesResponse)
async def get_anomalies(
    store_id: str,
    db: Session = Depends(get_db)
):
    """
    Detect active anomalies for a store.
    
    - BILLING_QUEUE_SPIKE
    - DEAD_ZONE
    - CONVERSION_DROP
    
    Each with severity and suggested action.
    """
    try:
        anomaly_service = AnomalyDetectionService(db)
        anomalies = anomaly_service.detect_anomalies(store_id)
        
        return AnomaliesResponse(
            store_id=store_id,
            anomalies=anomalies
        )
        
    except Exception as e:
        logger.error(
            "anomaly_detection_error",
            store_id=store_id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detect anomalies: {str(e)}"
        )


@app.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """
    System health check.
    
    - Service status
    - Last event timestamp per store
    - Stale feed warnings (>10 min lag)
    """
    try:
        health_service = HealthService(db)
        health_status = health_service.get_health_status()
        
        return HealthResponse(**health_status)
        
    except Exception as e:
        logger.error("health_check_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Health check failed"
        )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "Store Intelligence API",
        "version": "1.0.0",
        "status": "operational"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
