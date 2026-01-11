"""
Database Models - SQLAlchemy ORM models for CI Harvester.

See docs/design/DATA_MODEL.md for detailed schema documentation.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Text, DateTime,
    ForeignKey, Enum, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


def utcnow():
    """Return current UTC time."""
    return datetime.now(timezone.utc)


class CISource(Base):
    """CI platform instance (e.g., Jenkins server)."""
    __tablename__ = 'ci_sources'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    type = Column(String(50), nullable=False)  # 'jenkins', 'github_actions', etc.
    base_url = Column(String(2048), nullable=False)
    config = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    
    # Relationships
    jobs = relationship("Job", back_populates="source", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_ci_sources_type', 'type'),
        Index('idx_ci_sources_active', 'is_active', postgresql_where='is_active = true'),
    )


class Job(Base):
    """CI job/pipeline."""
    __tablename__ = 'jobs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey('ci_sources.id', ondelete='CASCADE'), nullable=False)
    external_id = Column(String(1024), nullable=False)
    name = Column(String(1024), nullable=False)
    url = Column(String(2048))
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    last_collected = Column(DateTime(timezone=True))
    
    # Relationships
    source = relationship("CISource", back_populates="jobs")
    builds = relationship("Build", back_populates="job", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('source_id', 'external_id', name='uq_jobs_source_external'),
        Index('idx_jobs_source', 'source_id'),
        Index('idx_jobs_active', 'is_active', postgresql_where='is_active = true'),
        Index('idx_jobs_last_collected', 'last_collected'),
    )


class Build(Base):
    """Individual build run."""
    __tablename__ = 'builds'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False)
    external_id = Column(String(255), nullable=False)
    number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default='unknown')
    result = Column(String(50))
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    duration_ms = Column(BigInteger)
    trigger_cause = Column(String(255))
    branch = Column(String(255))
    commit_sha = Column(String(64))
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    job = relationship("Job", back_populates="builds")
    logs = relationship("BuildLog", back_populates="build", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="build", cascade="all, delete-orphan")
    test_suites = relationship("TestSuite", back_populates="build", cascade="all, delete-orphan")
    test_results = relationship("TestResult", back_populates="build", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('job_id', 'external_id', name='uq_builds_job_external'),
        Index('idx_builds_job', 'job_id'),
        Index('idx_builds_job_number', 'job_id', 'number'),
        Index('idx_builds_started', 'started_at'),
        Index('idx_builds_result', 'result'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            'id': str(self.id),
            'job_id': str(self.job_id),
            'job_name': self.job.name if self.job else None,
            'number': self.number,
            'status': self.status,
            'result': self.result,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None,
            'duration_ms': self.duration_ms,
            'branch': self.branch,
            'commit_sha': self.commit_sha,
        }


class BuildLog(Base):
    """Build console log."""
    __tablename__ = 'build_logs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id = Column(UUID(as_uuid=True), ForeignKey('builds.id', ondelete='CASCADE'), nullable=False)
    log_type = Column(String(50), nullable=False, default='console')
    stage_name = Column(String(255))
    content = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    line_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    build = relationship("Build", back_populates="logs")
    
    __table_args__ = (
        Index('idx_build_logs_build', 'build_id'),
    )


class Artifact(Base):
    """Build artifact metadata."""
    __tablename__ = 'artifacts'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id = Column(UUID(as_uuid=True), ForeignKey('builds.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(1024), nullable=False)
    path = Column(String(2048), nullable=False)
    size_bytes = Column(BigInteger)
    content_type = Column(String(255))
    fingerprint = Column(String(64))
    stored_path = Column(String(2048))
    is_test_result = Column(Boolean, nullable=False, default=False)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    build = relationship("Build", back_populates="artifacts")
    
    __table_args__ = (
        Index('idx_artifacts_build', 'build_id'),
    )


class TestSuite(Base):
    """Test suite/file grouping."""
    __tablename__ = 'test_suites'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id = Column(UUID(as_uuid=True), ForeignKey('builds.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(1024), nullable=False)
    framework = Column(String(50), nullable=False, default='unknown')
    file_path = Column(String(2048))
    total_tests = Column(Integer, nullable=False, default=0)
    passed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)
    duration_ms = Column(BigInteger)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    build = relationship("Build", back_populates="test_suites")
    test_results = relationship("TestResult", back_populates="suite", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_test_suites_build', 'build_id'),
    )


class TestResult(Base):
    """Individual test case result."""
    __tablename__ = 'test_results'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    suite_id = Column(UUID(as_uuid=True), ForeignKey('test_suites.id', ondelete='CASCADE'))
    build_id = Column(UUID(as_uuid=True), ForeignKey('builds.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(1024), nullable=False)
    class_name = Column(String(1024))
    status = Column(String(50), nullable=False)
    duration_ms = Column(BigInteger)
    message = Column(Text)
    stack_trace = Column(Text)
    stdout = Column(Text)
    stderr = Column(Text)
    properties = Column(JSONB, nullable=False, default=dict)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    suite = relationship("TestSuite", back_populates="test_results")
    build = relationship("Build", back_populates="test_results")
    
    __table_args__ = (
        Index('idx_test_results_suite', 'suite_id'),
        Index('idx_test_results_build', 'build_id'),
        Index('idx_test_results_status', 'status'),
        Index('idx_test_results_name', 'name'),
    )
    
    @property
    def full_name(self) -> str:
        """Get full test name including class name."""
        if self.class_name:
            return f"{self.class_name}::{self.name}"
        return self.name


class CollectionRun(Base):
    """Audit log of collection operations."""
    __tablename__ = 'collection_runs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey('ci_sources.id', ondelete='SET NULL'))
    job_id = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='SET NULL'))
    run_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    builds_collected = Column(Integer, default=0)
    tests_collected = Column(Integer, default=0)
    error_message = Column(Text)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    __table_args__ = (
        Index('idx_collection_runs_source', 'source_id'),
        Index('idx_collection_runs_status', 'status'),
        Index('idx_collection_runs_started', 'started_at'),
    )


class APIKey(Base):
    """API keys for authentication."""
    __tablename__ = 'api_keys'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    key = Column(String(64), nullable=False, unique=True)
    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    __table_args__ = (
        Index('idx_api_keys_key', 'key'),
    )
