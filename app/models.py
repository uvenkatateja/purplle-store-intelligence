"""Database models and Pydantic schemas for Store Intelligence API."""

from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, JSON, Index, create_engine
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


# SQLAlchemy Models
class Event(Base):
    """Event table for storing all detection events."""
    
    __tablename__ = "events"
    
    event_id = Column(String, primary_key=True, index=True)
    store_id = Column(String, index=True, nullable=False)
    camera_id = Column(String, index=True, nullable=False)
    visitor_id = Column(String, index=True, nullable=False)
    event_type = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    zone_id = Column(String, nullable=True)
    dwell_ms = Column(Integer, default=0)
    is_staff = Column(Boolean, default=False, index=True)
    confidence = Column(Float, nullable=False)
    event_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_store_timestamp', 'store_id', 'timestamp'),
        Index('idx_visitor_timestamp', 'visitor_id', 'timestamp'),
        Index('idx_store_event_type', 'store_id', 'event_type'),
    )


# Pydantic Schemas
class EventMetadata(BaseModel):
    """Metadata for events."""
    
    queue_depth: Optional[int] = None
    sku_zone: Optional[str] = None
    session_seq: Optional[int] = None


class EventSchema(BaseModel):
    """Event schema matching the challenge specification."""
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: str
    timestamp: datetime
    zone_id: Optional[str] = None
    dwell_ms: int = 0
    is_staff: bool = False
    confidence: float
    metadata: Optional[EventMetadata] = None
    
    @field_validator('event_type')
    @classmethod
    def validate_event_type(cls, v):
        valid_types = [
            'ENTRY', 'EXIT', 'ZONE_ENTER', 'ZONE_EXIT', 'ZONE_DWELL',
            'BILLING_QUEUE_JOIN', 'BILLING_QUEUE_ABANDON', 'REENTRY'
        ]
        if v not in valid_types:
            raise ValueError(f'event_type must be one of {valid_types}')
        return v
    
    @field_validator('confidence')
    @classmethod
    def validate_confidence(cls, v):
        if not 0 <= v <= 1:
            raise ValueError('confidence must be between 0 and 1')
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "store_id": "STORE_BLR_001",
                "camera_id": "CAM_ENTRY_01",
                "visitor_id": "VIS_c8a2f1",
                "event_type": "ZONE_DWELL",
                "timestamp": "2026-04-10T14:22:10Z",
                "zone_id": "SKINCARE",
                "dwell_ms": 8400,
                "is_staff": False,
                "confidence": 0.91,
                "metadata": {
                    "queue_depth": None,
                    "sku_zone": "SKINCARE",
                    "session_seq": 5
                }
            }
        }


class IngestRequest(BaseModel):
    """Request model for batch event ingestion."""
    
    events: List[EventSchema] = Field(..., max_length=500)


class IngestResponse(BaseModel):
    """Response model for event ingestion."""
    
    success: bool
    ingested_count: int
    failed_count: int
    errors: List[Dict[str, Any]] = []


class MetricsResponse(BaseModel):
    """Response model for store metrics."""
    
    store_id: str
    date: str
    unique_visitors: int
    conversion_rate: float
    avg_dwell_per_zone: Dict[str, float]
    queue_depth: int
    abandonment_rate: float


class FunnelStage(BaseModel):
    """Single stage in the conversion funnel."""
    
    stage: str
    visitor_count: int
    drop_off_pct: float


class FunnelResponse(BaseModel):
    """Response model for conversion funnel."""
    
    store_id: str
    date: str
    funnel: List[FunnelStage]


class HeatmapZone(BaseModel):
    """Heatmap data for a single zone."""
    
    zone_id: str
    visit_frequency: int
    avg_dwell_ms: float
    normalized_score: int  # 0-100


class HeatmapResponse(BaseModel):
    """Response model for zone heatmap."""
    
    store_id: str
    date: str
    zones: List[HeatmapZone]
    data_confidence: str  # HIGH or LOW


class Anomaly(BaseModel):
    """Single anomaly detection."""
    
    anomaly_type: str
    severity: str  # INFO, WARN, CRITICAL
    description: str
    suggested_action: str
    detected_at: datetime


class AnomaliesResponse(BaseModel):
    """Response model for anomaly detection."""
    
    store_id: str
    anomalies: List[Anomaly]


class HealthResponse(BaseModel):
    """Response model for health check."""
    
    status: str
    last_event_per_store: Dict[str, Optional[datetime]]
    stale_feeds: List[str]


# Database setup
DATABASE_URL = "sqlite:///./store_intelligence.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for getting database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
