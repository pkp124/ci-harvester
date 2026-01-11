# CI Harvester - API Design

## 1. Overview

This document describes the REST API for querying CI Harvester data. The API provides read-only access to harvested build logs and test results, enabling dashboards, reporting tools, and integrations.

## 2. Technology Stack

- **Framework**: FastAPI (Python)
- **Serialization**: Pydantic
- **Documentation**: OpenAPI/Swagger (auto-generated)
- **Authentication**: API Keys or OAuth2 (configurable)
- **Rate Limiting**: slowapi

## 3. API Design Principles

1. **RESTful**: Follow REST conventions for resource naming and HTTP methods
2. **Versioned**: API versioned via URL prefix (`/api/v1/`)
3. **Paginated**: All list endpoints support pagination
4. **Filterable**: Support query parameters for filtering
5. **Consistent**: Uniform response format across endpoints
6. **Documented**: OpenAPI specification with examples

## 4. Base URL

```
Production: https://ci-harvester.example.com/api/v1
Development: http://localhost:8000/api/v1
```

## 5. Authentication

### 5.1 API Key Authentication

```http
GET /api/v1/builds
X-API-Key: your-api-key-here
```

### 5.2 OAuth2 (Optional)

```http
GET /api/v1/builds
Authorization: Bearer <access_token>
```

## 6. Common Response Format

### 6.1 Success Response

```json
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2024-01-15T12:34:56Z"
  }
}
```

### 6.2 List Response (Paginated)

```json
{
  "data": [ ... ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total_items": 150,
    "total_pages": 8,
    "has_next": true,
    "has_prev": false
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2024-01-15T12:34:56Z"
  }
}
```

### 6.3 Error Response

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Build with ID 'xyz' not found",
    "details": null
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2024-01-15T12:34:56Z"
  }
}
```

## 7. API Endpoints

### 7.1 CI Sources

#### List Sources

```http
GET /api/v1/sources
```

**Query Parameters:**
- `type`: Filter by source type (jenkins, github_actions, etc.)
- `active`: Filter by active status (true/false)

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "name": "jenkins-main",
      "type": "jenkins",
      "base_url": "https://jenkins.example.com",
      "is_active": true,
      "created_at": "2024-01-01T00:00:00Z",
      "stats": {
        "total_jobs": 50,
        "active_jobs": 45,
        "total_builds": 15000
      }
    }
  ],
  "pagination": { ... }
}
```

#### Get Source

```http
GET /api/v1/sources/{source_id}
```

### 7.2 Jobs

#### List Jobs

```http
GET /api/v1/jobs
```

**Query Parameters:**
- `source_id`: Filter by source
- `active`: Filter by active status
- `search`: Search job names (partial match)
- `page`: Page number (default: 1)
- `per_page`: Items per page (default: 20, max: 100)

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "source_id": "uuid",
      "source_name": "jenkins-main",
      "external_id": "folder/my-job",
      "name": "my-job",
      "url": "https://jenkins.example.com/job/folder/job/my-job/",
      "is_active": true,
      "last_collected": "2024-01-15T12:00:00Z",
      "stats": {
        "total_builds": 500,
        "recent_success_rate": 0.85,
        "avg_duration_ms": 300000
      }
    }
  ],
  "pagination": { ... }
}
```

#### Get Job

```http
GET /api/v1/jobs/{job_id}
```

#### Get Job Builds

```http
GET /api/v1/jobs/{job_id}/builds
```

**Query Parameters:**
- `result`: Filter by result (success, failure, unstable, aborted)
- `since`: Filter builds after this date (ISO 8601)
- `until`: Filter builds before this date
- `branch`: Filter by branch name
- `page`, `per_page`: Pagination

### 7.3 Builds

#### List Builds

```http
GET /api/v1/builds
```

**Query Parameters:**
- `job_id`: Filter by job
- `source_id`: Filter by source
- `result`: Filter by result
- `status`: Filter by status (running, completed, aborted)
- `since`: Start date filter
- `until`: End date filter
- `branch`: Filter by branch
- `commit`: Filter by commit SHA
- `has_failures`: Filter builds with test failures (true/false)
- `page`, `per_page`: Pagination

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "job_id": "uuid",
      "job_name": "my-job",
      "number": 142,
      "status": "completed",
      "result": "failure",
      "started_at": "2024-01-15T12:00:00Z",
      "finished_at": "2024-01-15T12:05:30Z",
      "duration_ms": 330000,
      "branch": "main",
      "commit_sha": "abc123def",
      "test_summary": {
        "total": 150,
        "passed": 145,
        "failed": 3,
        "skipped": 2,
        "errors": 0
      },
      "url": "https://jenkins.example.com/job/my-job/142/"
    }
  ],
  "pagination": { ... }
}
```

#### Get Build

```http
GET /api/v1/builds/{build_id}
```

**Response:**

```json
{
  "data": {
    "id": "uuid",
    "job_id": "uuid",
    "job_name": "my-job",
    "number": 142,
    "status": "completed",
    "result": "failure",
    "started_at": "2024-01-15T12:00:00Z",
    "finished_at": "2024-01-15T12:05:30Z",
    "duration_ms": 330000,
    "branch": "main",
    "commit_sha": "abc123def",
    "trigger_cause": "scm",
    "metadata": {
      "executor": "agent-01",
      "parameters": {
        "DEPLOY_ENV": "staging"
      }
    },
    "test_summary": {
      "total": 150,
      "passed": 145,
      "failed": 3,
      "skipped": 2,
      "errors": 0,
      "duration_ms": 45000
    },
    "artifacts": [
      {
        "id": "uuid",
        "name": "Test.xml",
        "path": "Testing/Test.xml",
        "size_bytes": 15000
      }
    ]
  }
}
```

#### Get Build Log

```http
GET /api/v1/builds/{build_id}/log
```

**Query Parameters:**
- `type`: Log type (console, stage) - default: console
- `stage`: Stage name (for pipeline jobs)
- `tail`: Return last N lines
- `search`: Search within log

**Response:**

```json
{
  "data": {
    "build_id": "uuid",
    "log_type": "console",
    "content": "Started by user admin\nRunning on agent-01...",
    "size_bytes": 50000,
    "line_count": 500
  }
}
```

#### Download Build Log (Raw)

```http
GET /api/v1/builds/{build_id}/log/download
Accept: text/plain
```

### 7.4 Test Results

#### List Test Results for Build

```http
GET /api/v1/builds/{build_id}/tests
```

**Query Parameters:**
- `status`: Filter by status (passed, failed, skipped, error)
- `suite`: Filter by suite name
- `search`: Search test names
- `page`, `per_page`: Pagination

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "build_id": "uuid",
      "suite_id": "uuid",
      "suite_name": "test_math",
      "name": "test_addition",
      "class_name": "TestSuite1",
      "full_name": "TestSuite1::test_addition",
      "status": "passed",
      "duration_ms": 123,
      "message": null,
      "has_output": false
    },
    {
      "id": "uuid",
      "build_id": "uuid",
      "suite_id": "uuid",
      "suite_name": "test_math",
      "name": "test_subtraction",
      "class_name": "TestSuite1",
      "full_name": "TestSuite1::test_subtraction",
      "status": "failed",
      "duration_ms": 456,
      "message": "Expected 5 but got 4",
      "has_output": true
    }
  ],
  "pagination": { ... }
}
```

#### Get Test Result Detail

```http
GET /api/v1/tests/{test_id}
```

**Response:**

```json
{
  "data": {
    "id": "uuid",
    "build_id": "uuid",
    "build_number": 142,
    "job_name": "my-job",
    "suite_id": "uuid",
    "suite_name": "test_math",
    "name": "test_subtraction",
    "class_name": "TestSuite1",
    "full_name": "TestSuite1::test_subtraction",
    "status": "failed",
    "duration_ms": 456,
    "message": "Expected 5 but got 4",
    "stack_trace": "File test_math.cpp, line 42\n...",
    "stdout": "Running test...\n",
    "stderr": null,
    "properties": {
      "command_line": "/path/to/test --gtest_filter=..."
    },
    "created_at": "2024-01-15T12:05:00Z"
  }
}
```

#### Get Test History

```http
GET /api/v1/tests/history
```

**Query Parameters:**
- `test_name`: Full test name (required)
- `job_id`: Limit to specific job
- `since`: Start date
- `limit`: Max results (default: 100)

**Response:**

```json
{
  "data": {
    "test_name": "TestSuite1::test_subtraction",
    "job_id": "uuid",
    "job_name": "my-job",
    "history": [
      {
        "build_id": "uuid",
        "build_number": 142,
        "started_at": "2024-01-15T12:00:00Z",
        "status": "failed",
        "duration_ms": 456,
        "message": "Expected 5 but got 4"
      },
      {
        "build_id": "uuid",
        "build_number": 141,
        "started_at": "2024-01-14T12:00:00Z",
        "status": "passed",
        "duration_ms": 123,
        "message": null
      }
    ],
    "stats": {
      "total_runs": 100,
      "passed": 95,
      "failed": 4,
      "skipped": 1,
      "failure_rate": 0.04,
      "avg_duration_ms": 150,
      "is_flaky": true
    }
  }
}
```

#### Search Failing Tests

```http
GET /api/v1/tests/failures
```

**Query Parameters:**
- `source_id`: Filter by source
- `job_id`: Filter by job
- `since`: Start date (default: last 7 days)
- `until`: End date
- `search`: Search test names
- `page`, `per_page`: Pagination

**Response:**

```json
{
  "data": [
    {
      "test_name": "TestSuite1::test_subtraction",
      "last_failure": "2024-01-15T12:00:00Z",
      "failure_count": 5,
      "total_runs": 20,
      "failure_rate": 0.25,
      "jobs_affected": [
        {
          "job_id": "uuid",
          "job_name": "my-job",
          "failures": 3
        }
      ],
      "latest_message": "Expected 5 but got 4",
      "is_flaky": true
    }
  ],
  "pagination": { ... }
}
```

### 7.5 Test Suites

#### List Test Suites for Build

```http
GET /api/v1/builds/{build_id}/suites
```

**Response:**

```json
{
  "data": [
    {
      "id": "uuid",
      "build_id": "uuid",
      "name": "test_math",
      "framework": "ctest",
      "total_tests": 10,
      "passed": 8,
      "failed": 1,
      "skipped": 1,
      "errors": 0,
      "duration_ms": 5000
    }
  ]
}
```

### 7.6 Analytics Endpoints

#### Build Trends

```http
GET /api/v1/analytics/build-trends
```

**Query Parameters:**
- `job_id`: Filter by job (required)
- `period`: Aggregation period (day, week, month)
- `since`: Start date
- `until`: End date

**Response:**

```json
{
  "data": {
    "job_id": "uuid",
    "job_name": "my-job",
    "period": "day",
    "trends": [
      {
        "date": "2024-01-15",
        "total_builds": 5,
        "successful": 4,
        "failed": 1,
        "success_rate": 0.8,
        "avg_duration_ms": 300000
      },
      {
        "date": "2024-01-14",
        "total_builds": 8,
        "successful": 7,
        "failed": 1,
        "success_rate": 0.875,
        "avg_duration_ms": 290000
      }
    ]
  }
}
```

#### Test Flakiness Report

```http
GET /api/v1/analytics/flaky-tests
```

**Query Parameters:**
- `job_id`: Filter by job
- `source_id`: Filter by source
- `min_runs`: Minimum runs to consider (default: 10)
- `since`: Start date (default: last 30 days)
- `threshold`: Flakiness threshold (default: 0.1 = 10%)

**Response:**

```json
{
  "data": [
    {
      "test_name": "TestSuite1::test_timing_sensitive",
      "job_name": "my-job",
      "total_runs": 100,
      "passed": 90,
      "failed": 10,
      "flakiness_score": 0.10,
      "avg_duration_ms": 500,
      "duration_variance": 200,
      "first_seen": "2024-01-01T00:00:00Z",
      "last_failure": "2024-01-15T12:00:00Z"
    }
  ],
  "pagination": { ... }
}
```

#### Test Duration Trends

```http
GET /api/v1/analytics/test-duration
```

**Query Parameters:**
- `test_name`: Test name (required)
- `job_id`: Filter by job
- `since`: Start date
- `until`: End date

**Response:**

```json
{
  "data": {
    "test_name": "TestSuite1::test_slow",
    "durations": [
      {
        "build_number": 142,
        "started_at": "2024-01-15T12:00:00Z",
        "duration_ms": 5000
      },
      {
        "build_number": 141,
        "started_at": "2024-01-14T12:00:00Z",
        "duration_ms": 4500
      }
    ],
    "stats": {
      "min_ms": 4000,
      "max_ms": 6000,
      "avg_ms": 4800,
      "p50_ms": 4700,
      "p90_ms": 5500,
      "p99_ms": 5900,
      "trend": "increasing"
    }
  }
}
```

### 7.7 System Endpoints

#### Health Check

```http
GET /api/v1/health
```

**Response:**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "components": {
    "database": "healthy",
    "airflow": "healthy"
  },
  "timestamp": "2024-01-15T12:34:56Z"
}
```

#### API Info

```http
GET /api/v1/info
```

**Response:**

```json
{
  "name": "CI Harvester API",
  "version": "1.0.0",
  "docs_url": "/docs",
  "openapi_url": "/openapi.json"
}
```

## 8. Implementation

### 8.1 FastAPI Application Structure

```python
# ci_harvester/api/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address

from ci_harvester.api.v1 import router as v1_router
from ci_harvester.api.middleware import RequestIdMiddleware

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="CI Harvester API",
    description="API for querying CI build logs and test results",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Rate limiting
app.state.limiter = limiter

# Routes
app.include_router(v1_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

### 8.2 Router Organization

```python
# ci_harvester/api/v1/__init__.py
from fastapi import APIRouter

from .sources import router as sources_router
from .jobs import router as jobs_router
from .builds import router as builds_router
from .tests import router as tests_router
from .analytics import router as analytics_router

router = APIRouter()

router.include_router(sources_router, prefix="/sources", tags=["Sources"])
router.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
router.include_router(builds_router, prefix="/builds", tags=["Builds"])
router.include_router(tests_router, prefix="/tests", tags=["Tests"])
router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
```

### 8.3 Example Endpoint Implementation

```python
# ci_harvester/api/v1/builds.py
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import datetime
from uuid import UUID

from ci_harvester.api.deps import get_db, get_current_user
from ci_harvester.api.schemas import (
    BuildListResponse, BuildDetailResponse, 
    PaginationParams, BuildFilters
)
from ci_harvester.db.models import Build, Job, TestSuite
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

router = APIRouter()

@router.get("", response_model=BuildListResponse)
async def list_builds(
    job_id: Optional[UUID] = None,
    source_id: Optional[UUID] = None,
    result: Optional[str] = None,
    status: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    branch: Optional[str] = None,
    has_failures: Optional[bool] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List builds with optional filters."""
    
    query = db.query(Build).join(Job)
    
    # Apply filters
    if job_id:
        query = query.filter(Build.job_id == job_id)
    if source_id:
        query = query.filter(Job.source_id == source_id)
    if result:
        query = query.filter(Build.result == result)
    if status:
        query = query.filter(Build.status == status)
    if since:
        query = query.filter(Build.started_at >= since)
    if until:
        query = query.filter(Build.started_at <= until)
    if branch:
        query = query.filter(Build.branch == branch)
    if has_failures is not None:
        if has_failures:
            query = query.join(TestSuite).filter(TestSuite.failed > 0)
        else:
            query = query.outerjoin(TestSuite).filter(
                (TestSuite.id == None) | (TestSuite.failed == 0)
            )
    
    # Get total count
    total = query.count()
    
    # Paginate and fetch
    builds = query.order_by(Build.started_at.desc()) \
        .offset((page - 1) * per_page) \
        .limit(per_page) \
        .all()
    
    return BuildListResponse(
        data=[build.to_dict() for build in builds],
        pagination={
            "page": page,
            "per_page": per_page,
            "total_items": total,
            "total_pages": (total + per_page - 1) // per_page,
            "has_next": page * per_page < total,
            "has_prev": page > 1
        }
    )

@router.get("/{build_id}", response_model=BuildDetailResponse)
async def get_build(
    build_id: UUID,
    db: Session = Depends(get_db),
):
    """Get build details."""
    
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    
    return BuildDetailResponse(data=build.to_detail_dict())

@router.get("/{build_id}/log")
async def get_build_log(
    build_id: UUID,
    log_type: str = "console",
    tail: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get build log."""
    
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    
    log = db.query(BuildLog).filter(
        BuildLog.build_id == build_id,
        BuildLog.log_type == log_type
    ).first()
    
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    
    content = log.content
    
    # Apply tail filter
    if tail:
        lines = content.split('\n')
        content = '\n'.join(lines[-tail:])
    
    # Apply search filter
    if search:
        lines = content.split('\n')
        content = '\n'.join(line for line in lines if search in line)
    
    return {
        "data": {
            "build_id": str(build_id),
            "log_type": log_type,
            "content": content,
            "size_bytes": log.size_bytes,
            "line_count": log.line_count
        }
    }
```

### 8.4 Pydantic Schemas

```python
# ci_harvester/api/schemas.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from enum import Enum

class TestStatus(str, Enum):
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    error = "error"

class BuildResult(str, Enum):
    success = "success"
    failure = "failure"
    unstable = "unstable"
    aborted = "aborted"

# Response models
class PaginationInfo(BaseModel):
    page: int
    per_page: int
    total_items: int
    total_pages: int
    has_next: bool
    has_prev: bool

class Meta(BaseModel):
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class TestSummary(BaseModel):
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration_ms: Optional[int] = None

class BuildListItem(BaseModel):
    id: UUID
    job_id: UUID
    job_name: str
    number: int
    status: str
    result: Optional[BuildResult]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    branch: Optional[str]
    commit_sha: Optional[str]
    test_summary: Optional[TestSummary]
    url: Optional[str]

class BuildListResponse(BaseModel):
    data: List[BuildListItem]
    pagination: PaginationInfo
    meta: Meta = Field(default_factory=Meta)

class BuildDetail(BuildListItem):
    trigger_cause: Optional[str]
    metadata: Dict[str, Any] = {}
    artifacts: List[Dict[str, Any]] = []

class BuildDetailResponse(BaseModel):
    data: BuildDetail
    meta: Meta = Field(default_factory=Meta)

class TestResultItem(BaseModel):
    id: UUID
    build_id: UUID
    suite_id: Optional[UUID]
    suite_name: Optional[str]
    name: str
    class_name: Optional[str]
    full_name: str
    status: TestStatus
    duration_ms: Optional[int]
    message: Optional[str]
    has_output: bool

class TestResultListResponse(BaseModel):
    data: List[TestResultItem]
    pagination: PaginationInfo
    meta: Meta = Field(default_factory=Meta)

class TestResultDetail(TestResultItem):
    stack_trace: Optional[str]
    stdout: Optional[str]
    stderr: Optional[str]
    properties: Dict[str, Any] = {}
    created_at: datetime

class TestResultDetailResponse(BaseModel):
    data: TestResultDetail
    meta: Meta = Field(default_factory=Meta)
```

### 8.5 Authentication

```python
# ci_harvester/api/auth.py
from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN

from ci_harvester.db import get_session
from ci_harvester.db.models import APIKey

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def get_api_key(
    api_key: str = Security(api_key_header),
):
    """Validate API key."""
    if not api_key:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="API key required"
        )
    
    with get_session() as session:
        key_record = session.query(APIKey).filter(
            APIKey.key == api_key,
            APIKey.is_active == True
        ).first()
        
        if not key_record:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Invalid API key"
            )
        
        return key_record

# Use in endpoints
@router.get("/builds")
async def list_builds(
    api_key: APIKey = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    ...
```

## 9. Error Handling

### 9.1 Error Codes

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | BAD_REQUEST | Invalid request parameters |
| 401 | UNAUTHORIZED | Missing authentication |
| 403 | FORBIDDEN | Invalid or expired credentials |
| 404 | NOT_FOUND | Resource not found |
| 422 | VALIDATION_ERROR | Request validation failed |
| 429 | RATE_LIMITED | Too many requests |
| 500 | INTERNAL_ERROR | Server error |

### 9.2 Exception Handler

```python
# ci_harvester/api/exceptions.py
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.detail if isinstance(exc.detail, str) else "ERROR",
                "message": str(exc.detail),
                "details": None
            },
            "meta": {
                "request_id": getattr(request.state, 'request_id', None),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": exc.errors()
            },
            "meta": {
                "request_id": getattr(request.state, 'request_id', None),
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )
```

## 10. Rate Limiting

```python
# ci_harvester/api/middleware.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"]
)

# Per-endpoint limits
@router.get("/builds/{build_id}/log")
@limiter.limit("30/minute")  # Lower limit for expensive operations
async def get_build_log(...):
    ...
```

## 11. OpenAPI Documentation

The API automatically generates OpenAPI documentation at:
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

```python
# Custom OpenAPI schema
app = FastAPI(
    title="CI Harvester API",
    description="""
    API for querying CI/CD build logs and test results.
    
    ## Features
    - Query builds and test results from multiple CI platforms
    - Search and filter test failures
    - Analyze test trends and flakiness
    
    ## Authentication
    Use API key authentication via the `X-API-Key` header.
    """,
    version="1.0.0",
    contact={
        "name": "CI Harvester Team",
        "email": "team@example.com"
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT"
    },
    servers=[
        {"url": "https://ci-harvester.example.com", "description": "Production"},
        {"url": "http://localhost:8000", "description": "Development"}
    ]
)
```
