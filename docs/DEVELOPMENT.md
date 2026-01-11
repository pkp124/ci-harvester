# CI Harvester Development Guide

This guide provides detailed instructions for setting up and working with the CI Harvester development environment.

## Table of Contents

- [Environment Setup](#environment-setup)
- [Development Workflow](#development-workflow)
- [Testing Strategy](#testing-strategy)
- [Database Management](#database-management)
- [Airflow Development](#airflow-development)
- [API Development](#api-development)
- [Debugging](#debugging)
- [Performance Considerations](#performance-considerations)

## Environment Setup

### Prerequisites

- Python 3.11 or higher
- PostgreSQL 15+
- Docker & Docker Compose
- Git

### Quick Start

```bash
# 1. Clone repository
git clone <repository-url>
cd ci-harvester

# 2. Create Python virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env with your settings

# 5. Start development services
docker-compose -f docker/docker-compose.yml up -d postgres-data redis

# 6. Initialize database
python -m ci_harvester.db.init

# 7. Verify setup
pytest -x  # Run tests, stop on first failure
```

### Full Stack Development

For full stack development with Airflow:

```bash
# Start all services
docker-compose -f docker/docker-compose.yml up -d

# Access points:
# - Airflow UI: http://localhost:8080 (admin/admin)
# - API: http://localhost:8000/docs
# - Database: localhost:5432 (ci_harvester/ci_harvester)
# - Adminer: http://localhost:8081
```

### Environment Variables

Key environment variables (see `.env.example` for full list):

```bash
# Database
DATABASE_URL=postgresql://ci_harvester:password@localhost:5432/ci_harvester

# Jenkins (for testing with real Jenkins)
JENKINS_URL=https://jenkins.example.com
JENKINS_USERNAME=your-username
JENKINS_API_TOKEN=your-token

# API
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=DEBUG
```

## Development Workflow

### 1. Understand Requirements

Before coding:
1. Review the relevant design doc in `docs/design/`
2. Understand how changes fit the data model
3. Identify affected components

### 2. TDD Cycle

**Always follow Test-Driven Development:**

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    RED       │────▶│    GREEN     │────▶│   REFACTOR   │
│ Write Test   │     │ Make Pass    │     │  Clean Up    │
└──────────────┘     └──────────────┘     └──────────────┘
       ▲                                         │
       └─────────────────────────────────────────┘
```

**Example workflow:**

```bash
# 1. Create test file (if new)
touch tests/parsers/test_new_feature.py

# 2. Write failing test
# Edit tests/parsers/test_new_feature.py

# 3. Run test - should fail
pytest tests/parsers/test_new_feature.py -v

# 4. Implement feature
# Edit ci_harvester/parsers/...

# 5. Run test - should pass
pytest tests/parsers/test_new_feature.py -v

# 6. Run all tests - should still pass
pytest

# 7. Check coverage
pytest --cov=ci_harvester --cov-report=html
open htmlcov/index.html
```

### 3. Branch Strategy

```bash
# Feature branch
git checkout -b feat/add-gitlab-collector

# Bug fix
git checkout -b fix/parser-handles-empty-xml

# Keep branch updated
git fetch origin
git rebase origin/main
```

### 4. Commit Guidelines

Use [Conventional Commits](https://www.conventionalcommits.org/):

```bash
git commit -m "feat(collector): add GitLab CI collector

- Implement GitLabCollector class
- Support project and group level pipelines  
- Add authentication via personal access token

Closes #42"
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

## Testing Strategy

### Test Pyramid

```
         /\
        /  \      E2E Tests (few)
       /────\     
      /      \    Integration Tests
     /────────\   
    /          \  Unit Tests (many)
   /────────────\ 
```

### Unit Tests

Fast, isolated tests for individual functions:

```python
# tests/parsers/test_ctest.py

def test_parse_test_name_simple():
    """Unit test - no dependencies."""
    parser = CTestXMLParser()
    name, class_name, suite = parser._parse_test_name("test_simple")
    
    assert name == "test_simple"
    assert class_name is None
    assert suite is None
```

### Integration Tests

Test component interactions:

```python
# tests/parsers/test_ctest.py

@pytest.mark.integration
def test_save_creates_test_executions(db_session, sample_build):
    """Integration test - uses database."""
    parser = CTestXMLParser()
    report = parser.parse(sample_ctest_xml)
    
    saver = CTestResultSaver(db_session)
    stats = saver.save(report, sample_build)
    
    assert stats['executions_created'] == 3
    
    # Verify in database
    executions = db_session.query(TestExecution).all()
    assert len(executions) == 3
```

### Test Markers

```python
# Mark slow tests
@pytest.mark.slow
def test_process_large_file():
    ...

# Mark integration tests
@pytest.mark.integration
def test_database_operation():
    ...

# Skip under certain conditions
@pytest.mark.skipif(not JENKINS_URL, reason="No Jenkins configured")
def test_real_jenkins_connection():
    ...
```

### Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=ci_harvester --cov-report=term-missing

# Only unit tests (fast)
pytest -m "not integration and not slow"

# Parallel execution
pytest -n auto

# Stop on first failure
pytest -x

# Re-run failed tests
pytest --lf

# Verbose with stdout capture disabled
pytest -v -s
```

### Fixtures

Common fixtures in `tests/conftest.py`:

```python
# Database session
def test_with_db(db_session):
    db_session.query(Product).all()

# Sample entities
def test_with_product(sample_product):
    assert sample_product.name == "TestProduct"

def test_with_job(sample_job):
    assert sample_job.ci_source == "jenkins"

def test_with_build(sample_build):
    assert sample_build.number == 42

# Sample XML
def test_parse(sample_ctest_xml):
    parser.parse(sample_ctest_xml)
```

## Database Management

### Schema Migrations

Using Alembic for migrations:

```bash
# Create a new migration
alembic revision --autogenerate -m "add flakiness column to tests"

# Apply migrations
alembic upgrade head

# Rollback one version
alembic downgrade -1

# Show current version
alembic current

# Show migration history
alembic history
```

### Manual Database Access

```bash
# Connect via psql
psql postgresql://ci_harvester:ci_harvester@localhost/ci_harvester

# Or use Adminer at http://localhost:8081
```

### Common Queries

```sql
-- Test summary for a build
SELECT 
    t.full_name,
    te.status,
    te.duration_ms
FROM test_executions te
JOIN tests t ON te.test_id = t.id
WHERE te.build_id = 'uuid-here';

-- Flaky tests (last 30 days)
SELECT 
    t.full_name,
    COUNT(*) as runs,
    COUNT(*) FILTER (WHERE te.status = 'passed') as passed,
    COUNT(*) FILTER (WHERE te.status = 'failed') as failed
FROM tests t
JOIN test_executions te ON t.id = te.test_id
JOIN builds b ON te.build_id = b.id
WHERE b.created_at > NOW() - INTERVAL '30 days'
GROUP BY t.id, t.full_name
HAVING COUNT(*) FILTER (WHERE te.status = 'passed') > 0
   AND COUNT(*) FILTER (WHERE te.status = 'failed') > 0;
```

### Resetting Development Database

```bash
# Drop and recreate
docker-compose -f docker/docker-compose.yml down -v
docker-compose -f docker/docker-compose.yml up -d postgres-data
python -m ci_harvester.db.init
```

## Airflow Development

### DAG Development

DAGs are in the `dags/` directory:

```python
# dags/my_new_dag.py
from airflow import DAG
from airflow.decorators import task

with DAG(
    dag_id='my_new_dag',
    schedule_interval='@hourly',
    ...
) as dag:
    
    @task
    def my_task():
        from ci_harvester.collectors import get_collector
        # Use ci_harvester package
```

### Testing DAGs

```bash
# Parse DAG file
python dags/discover_jobs.py

# Test specific task
airflow tasks test discover_jobs get_active_sources 2024-01-01

# Run DAG locally
airflow dags test discover_jobs 2024-01-01
```

### Airflow UI

Access at http://localhost:8080 (default: admin/admin)

- View DAG runs and logs
- Trigger manual runs
- Monitor task execution

## API Development

### Running the API Server

```bash
# Development mode with auto-reload
uvicorn ci_harvester.api.main:app --reload --port 8000

# Access docs at:
# - Swagger UI: http://localhost:8000/docs
# - ReDoc: http://localhost:8000/redoc
```

### Adding Endpoints

1. Define Pydantic schemas:

```python
# ci_harvester/api/schemas.py
class TestResponse(BaseModel):
    id: UUID
    full_name: str
    status: str
    duration_ms: Optional[int]
```

2. Implement endpoint:

```python
# ci_harvester/api/v1/tests.py
@router.get("/{test_id}", response_model=TestResponse)
async def get_test(test_id: UUID, db: Session = Depends(get_db)):
    test = db.query(Test).filter(Test.id == test_id).first()
    if not test:
        raise HTTPException(404, "Test not found")
    return test
```

3. Write tests:

```python
# tests/api/test_tests.py
def test_get_test(client, sample_test):
    response = client.get(f"/api/v1/tests/{sample_test.id}")
    assert response.status_code == 200
    assert response.json()["full_name"] == sample_test.full_name
```

## Debugging

### Logging

Use structured logging:

```python
import structlog

logger = structlog.get_logger()

logger.info("processing_build", 
    job=job_name, 
    build=build_number,
    tests_found=len(tests))

logger.error("parse_failed",
    file=filename,
    error=str(e),
    line=line_number)
```

### Debugging Tests

```python
# Use breakpoint
def test_something():
    result = function_under_test()
    breakpoint()  # Drops into pdb
    assert result == expected

# Run with debugger
pytest --pdb  # Drop into pdb on failure
pytest --pdb-first  # Drop into pdb on first failure
```

### Database Query Logging

```python
# Enable SQLAlchemy query logging
import logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
```

## Performance Considerations

### Database

- Use bulk operations for inserting many records
- Add indexes for common query patterns
- Use `explain analyze` for slow queries
- Consider partitioning for large tables

```python
# Bulk insert
session.bulk_insert_mappings(TestExecution, [
    {'build_id': b.id, 'test_id': t.id, ...}
    for t in tests
])

# Avoid N+1 queries
query = session.query(Build).options(
    joinedload(Build.test_executions)
)
```

### Collectors

- Implement rate limiting for CI platform APIs
- Use connection pooling
- Cache job discovery results
- Process builds in batches

### Parsers

- Stream large XML files
- Truncate large output fields
- Use efficient string operations

```python
# Stream large files
for event, elem in ET.iterparse(file_path, events=['end']):
    if elem.tag == 'Test':
        process_test(elem)
        elem.clear()  # Free memory
```

## Troubleshooting

### Common Issues

**Tests fail with database errors:**
```bash
# Reset test database
docker-compose -f docker/docker-compose.yml restart postgres-data
```

**Import errors:**
```bash
# Ensure package is installed in editable mode
pip install -e .
```

**Airflow DAG not appearing:**
```bash
# Check for syntax errors
python dags/my_dag.py

# Check Airflow logs
docker-compose logs airflow-scheduler
```

**API connection refused:**
```bash
# Check if service is running
docker-compose ps

# Check logs
docker-compose logs api
```
