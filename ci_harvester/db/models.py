"""
Database Models - SQLAlchemy ORM models for CI Harvester.

Hierarchy:
- Products → Jobs → Builds
- Jobs → Tests
- Builds → Test Executions → CTest Measurements

See docs/design/DATA_MODEL.md for detailed schema documentation.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Text, DateTime,
    ForeignKey, Float, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


def utcnow():
    """Return current UTC time."""
    return datetime.now(timezone.utc)


# =============================================================================
# Products
# =============================================================================

class Product(Base):
    """Top-level product/project grouping."""
    __tablename__ = 'products'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    repository_url = Column(String(2048))
    metadata = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    
    # Relationships
    jobs = relationship("Job", back_populates="product", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_products_name', 'name'),
        Index('idx_products_active', 'is_active', postgresql_where='is_active = true'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'repository_url': self.repository_url,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


# =============================================================================
# Jobs
# =============================================================================

class Job(Base):
    """CI job/pipeline belonging to a product."""
    __tablename__ = 'jobs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    external_id = Column(String(1024), nullable=False)  # CI platform job identifier
    name = Column(String(1024), nullable=False)
    url = Column(String(2048))
    ci_source = Column(String(50), nullable=False)  # 'jenkins', 'github_actions', etc.
    ci_source_url = Column(String(2048))  # Base URL of CI server
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    last_collected = Column(DateTime(timezone=True))
    
    # Relationships
    product = relationship("Product", back_populates="jobs")
    builds = relationship("Build", back_populates="job", cascade="all, delete-orphan")
    tests = relationship("Test", back_populates="job", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('product_id', 'external_id', name='uq_jobs_product_external'),
        Index('idx_jobs_product', 'product_id'),
        Index('idx_jobs_ci_source', 'ci_source'),
        Index('idx_jobs_active', 'is_active', postgresql_where='is_active = true'),
        Index('idx_jobs_last_collected', 'last_collected'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'product_id': str(self.product_id),
            'product_name': self.product.name if self.product else None,
            'external_id': self.external_id,
            'name': self.name,
            'url': self.url,
            'ci_source': self.ci_source,
            'is_active': self.is_active,
            'last_collected': self.last_collected.isoformat() if self.last_collected else None,
        }


# =============================================================================
# Builds
# =============================================================================

class Build(Base):
    """Individual build run of a job."""
    __tablename__ = 'builds'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False)
    external_id = Column(String(255), nullable=False)
    number = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default='unknown')  # pending, running, completed, aborted
    result = Column(String(50))  # success, failure, unstable, aborted, not_built
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    duration_ms = Column(BigInteger)
    trigger_cause = Column(String(255))
    branch = Column(String(255))
    commit_sha = Column(String(64))
    commit_message = Column(Text)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    job = relationship("Job", back_populates="builds")
    logs = relationship("BuildLog", back_populates="build", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="build", cascade="all, delete-orphan")
    test_executions = relationship("TestExecution", back_populates="build", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('job_id', 'number', name='uq_builds_job_number'),
        Index('idx_builds_job', 'job_id'),
        Index('idx_builds_job_number', 'job_id', 'number'),
        Index('idx_builds_started', 'started_at'),
        Index('idx_builds_result', 'result'),
        Index('idx_builds_branch', 'branch', postgresql_where='branch IS NOT NULL'),
        Index('idx_builds_commit', 'commit_sha', postgresql_where='commit_sha IS NOT NULL'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
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
    
    def get_test_summary(self) -> Dict[str, int]:
        """Get test execution summary for this build."""
        summary = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'error': 0,
        }
        for te in self.test_executions:
            summary['total'] += 1
            if te.status in summary:
                summary[te.status] += 1
        return summary


# =============================================================================
# Tests (Test Definitions)
# =============================================================================

class Test(Base):
    """Test definition belonging to a job (persistent across builds)."""
    __tablename__ = 'tests'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(1024), nullable=False)
    full_name = Column(String(2048), nullable=False)  # Includes class/suite name
    class_name = Column(String(1024))
    suite_name = Column(String(1024))
    file_path = Column(String(2048))
    description = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    
    # Relationships
    job = relationship("Job", back_populates="tests")
    executions = relationship("TestExecution", back_populates="test", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('job_id', 'full_name', name='uq_tests_job_fullname'),
        Index('idx_tests_job', 'job_id'),
        Index('idx_tests_name', 'name'),
        Index('idx_tests_full_name', 'full_name'),
        Index('idx_tests_class', 'class_name', postgresql_where='class_name IS NOT NULL'),
        Index('idx_tests_suite', 'suite_name', postgresql_where='suite_name IS NOT NULL'),
        Index('idx_tests_active', 'is_active', postgresql_where='is_active = true'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'job_id': str(self.job_id),
            'name': self.name,
            'full_name': self.full_name,
            'class_name': self.class_name,
            'suite_name': self.suite_name,
            'file_path': self.file_path,
            'is_active': self.is_active,
            'first_seen_at': self.first_seen_at.isoformat() if self.first_seen_at else None,
            'last_seen_at': self.last_seen_at.isoformat() if self.last_seen_at else None,
        }


# =============================================================================
# Test Executions
# =============================================================================

class TestExecution(Base):
    """Execution of a test in a specific build."""
    __tablename__ = 'test_executions'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id = Column(UUID(as_uuid=True), ForeignKey('builds.id', ondelete='CASCADE'), nullable=False)
    test_id = Column(UUID(as_uuid=True), ForeignKey('tests.id', ondelete='CASCADE'), nullable=False)
    status = Column(String(50), nullable=False)  # passed, failed, skipped, error, timeout, not_run
    duration_ms = Column(BigInteger)
    message = Column(Text)  # Failure/error message
    stack_trace = Column(Text)
    stdout = Column(Text)
    stderr = Column(Text)
    command_line = Column(Text)
    exit_code = Column(Integer)
    retry_count = Column(Integer, default=0)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    build = relationship("Build", back_populates="test_executions")
    test = relationship("Test", back_populates="executions")
    measurements = relationship("CTestMeasurement", back_populates="test_execution", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('build_id', 'test_id', name='uq_test_executions_build_test'),
        Index('idx_test_executions_build', 'build_id'),
        Index('idx_test_executions_test', 'test_id'),
        Index('idx_test_executions_status', 'status'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'build_id': str(self.build_id),
            'test_id': str(self.test_id),
            'test_name': self.test.full_name if self.test else None,
            'status': self.status,
            'duration_ms': self.duration_ms,
            'message': self.message,
            'has_output': bool(self.stdout or self.stderr),
        }
    
    def to_detail_dict(self) -> Dict[str, Any]:
        """Full details including output and measurements."""
        result = self.to_dict()
        result.update({
            'stack_trace': self.stack_trace,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'command_line': self.command_line,
            'exit_code': self.exit_code,
            'retry_count': self.retry_count,
            'measurements': [m.to_dict() for m in self.measurements],
        })
        return result


# =============================================================================
# CTest Measurements
# =============================================================================

class CTestMeasurement(Base):
    """CTest measurement captured during test execution."""
    __tablename__ = 'ctest_measurements'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_execution_id = Column(UUID(as_uuid=True), ForeignKey('test_executions.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # 'numeric/double', 'text/string', etc.
    value_numeric = Column(Float)
    value_text = Column(Text)
    unit = Column(String(50))  # 'seconds', 'bytes', 'percent', etc.
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    test_execution = relationship("TestExecution", back_populates="measurements")
    
    __table_args__ = (
        Index('idx_ctest_measurements_execution', 'test_execution_id'),
        Index('idx_ctest_measurements_name', 'name'),
        Index('idx_ctest_measurements_type', 'type'),
    )
    
    @property
    def value(self):
        """Get the measurement value (numeric or text)."""
        if self.value_numeric is not None:
            return self.value_numeric
        return self.value_text
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': str(self.id),
            'name': self.name,
            'type': self.type,
            'value': self.value,
            'unit': self.unit,
        }


# =============================================================================
# Build Logs
# =============================================================================

class BuildLog(Base):
    """Build console log."""
    __tablename__ = 'build_logs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    build_id = Column(UUID(as_uuid=True), ForeignKey('builds.id', ondelete='CASCADE'), nullable=False)
    log_type = Column(String(50), nullable=False, default='console')  # console, stage
    stage_name = Column(String(255))
    content = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    line_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    # Relationships
    build = relationship("Build", back_populates="logs")
    
    __table_args__ = (
        Index('idx_build_logs_build', 'build_id'),
        Index('idx_build_logs_type', 'log_type'),
    )


# =============================================================================
# Artifacts
# =============================================================================

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
        Index('idx_artifacts_test_result', 'build_id', postgresql_where='is_test_result = true'),
    )


# =============================================================================
# Collection Runs (Audit Log)
# =============================================================================

class CollectionRun(Base):
    """Audit log of collection operations."""
    __tablename__ = 'collection_runs'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey('products.id', ondelete='SET NULL'))
    job_id = Column(UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='SET NULL'))
    run_type = Column(String(50), nullable=False)  # 'discover', 'collect', 'full'
    status = Column(String(50), nullable=False)  # 'started', 'completed', 'failed', 'partial'
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    builds_collected = Column(Integer, default=0)
    tests_collected = Column(Integer, default=0)
    error_message = Column(Text)
    metadata = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    
    __table_args__ = (
        Index('idx_collection_runs_product', 'product_id'),
        Index('idx_collection_runs_job', 'job_id'),
        Index('idx_collection_runs_status', 'status'),
        Index('idx_collection_runs_started', 'started_at'),
    )


# =============================================================================
# API Keys
# =============================================================================

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
