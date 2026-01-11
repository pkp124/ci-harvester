# AI Agent Guidelines for CI Harvester

This document provides context and guidelines for AI coding assistants working on this project.

## Quick Reference

| Aspect | Guideline |
|--------|-----------|
| **TDD** | ALWAYS write tests first |
| **Design Docs** | Review before implementing |
| **Data Model** | Products → Jobs → Builds; Jobs → Tests |
| **Testing** | pytest, 80%+ coverage |
| **Style** | black, ruff, type hints required |
| **Commits** | Conventional commits format |

## Project Overview

**CI Harvester** scrapes CI/CD systems (starting with Jenkins) for build logs and test results (starting with CTest), stores them in PostgreSQL, and provides a REST API for querying.

### Core Technologies
- **Language**: Python 3.11+
- **Database**: PostgreSQL + SQLAlchemy ORM
- **Orchestration**: Apache Airflow
- **API**: FastAPI
- **Testing**: pytest

### Data Model Hierarchy

```
Product (e.g., "MyProduct")
  └── Job (e.g., "linux-build-test")  
        ├── Test (definition, persistent)
        │     └── "MathTests::test_addition"
        └── Build (#42)
              └── TestExecution (test + build = execution)
                    └── CTestMeasurement ("Execution Time": 0.5s)
```

## Mandatory Practices

### 1. Test-Driven Development (TDD)

**Every feature or fix MUST follow TDD:**

```python
# Step 1: Write the test FIRST
def test_new_feature():
    result = my_new_function("input")
    assert result == "expected"

# Step 2: Run test, see it fail
# Step 3: Implement minimum code to pass
# Step 4: Refactor while keeping tests green
```

**Test file location**: Mirror source structure in `tests/`
```
ci_harvester/parsers/ctest.py  →  tests/parsers/test_ctest.py
ci_harvester/collectors/jenkins.py  →  tests/collectors/test_jenkins.py
```

### 2. Design Documentation Review

**Before implementing significant changes:**

1. Read relevant design doc in `docs/design/`
2. Check if changes affect data model
3. Update design doc if architecture changes

**Key design docs:**
- `docs/design/DESIGN.md` - Architecture overview
- `docs/design/DATA_MODEL.md` - Database schema ⚠️ IMPORTANT
- `docs/design/JENKINS_INTEGRATION.md` - Jenkins collector
- `docs/design/CTEST_PARSER.md` - CTest parser
- `docs/design/API_DESIGN.md` - REST API endpoints

### 3. Code Patterns

**Database Operations:**
```python
# Always use context manager
with get_session() as session:
    product = session.query(Product).filter_by(name=name).first()

# Bulk operations for performance
session.bulk_insert_mappings(TestExecution, execution_dicts)
```

**Error Handling:**
```python
# Specific exceptions with context
class CTestParseError(Exception):
    """Failed to parse CTest XML."""
    pass

raise CTestParseError(f"Invalid XML structure: missing <Testing> element")
```

**Type Hints Required:**
```python
from typing import List, Optional
from uuid import UUID

def get_test_history(test_id: UUID, limit: int = 100) -> List[TestExecution]:
    ...
```

## Common Tasks

### Adding a New Parser

1. **Write tests first** in `tests/parsers/test_{format}.py`
2. Create parser class implementing `BaseParser`
3. Register in `ParserFactory`
4. Update `docs/design/{FORMAT}_PARSER.md`

```python
# Required interface
class NewFormatParser(BaseParser):
    def can_parse(self, content: bytes, filename: str) -> bool:
        ...
    
    def parse(self, content: bytes) -> CTestReport:
        ...
```

### Adding a New Collector

1. **Write tests first** in `tests/collectors/test_{platform}.py`
2. Create collector in `ci_harvester/collectors/{platform}.py`
3. Use `@register_collector("{platform}")` decorator
4. Create design doc `docs/design/{PLATFORM}_INTEGRATION.md`

```python
@register_collector("github_actions")
class GitHubActionsCollector:
    def discover_jobs(self) -> List[JobInfo]:
        ...
    
    def get_builds(self, job_id: str, since: datetime) -> List[BuildInfo]:
        ...
```

### Adding an API Endpoint

1. **Write tests first** in `tests/api/test_{resource}.py`
2. Add Pydantic schemas in `ci_harvester/api/schemas.py`
3. Implement in appropriate router under `ci_harvester/api/v1/`
4. Update `docs/design/API_DESIGN.md`

### Modifying the Data Model

1. **Update design doc first**: `docs/design/DATA_MODEL.md`
2. Modify SQLAlchemy models in `ci_harvester/db/models.py`
3. Create Alembic migration
4. Update affected tests

## Important Files

| File | Purpose |
|------|---------|
| `ci_harvester/db/models.py` | SQLAlchemy ORM models |
| `ci_harvester/collectors/jenkins.py` | Jenkins API integration |
| `ci_harvester/parsers/ctest.py` | CTest XML/JUnit parsing |
| `dags/discover_jobs.py` | Airflow job discovery DAG |
| `tests/conftest.py` | Shared pytest fixtures |

## Fixtures Available in Tests

```python
# Database
@pytest.fixture
def db_session(engine):  # SQLAlchemy session

# Sample data
@pytest.fixture
def sample_product(db_session):  # Product instance

@pytest.fixture
def sample_job(db_session, sample_product):  # Job instance

@pytest.fixture  
def sample_build(db_session, sample_job):  # Build instance

@pytest.fixture
def sample_test(db_session, sample_job):  # Test instance

# Test data
@pytest.fixture
def sample_ctest_xml():  # CTest XML bytes

@pytest.fixture
def sample_junit_xml():  # JUnit XML bytes

@pytest.fixture
def sample_ctest_with_measurements():  # CTest with measurements
```

## Running Tests

```bash
# All tests
pytest

# Specific file
pytest tests/parsers/test_ctest.py

# Specific test
pytest tests/parsers/test_ctest.py::TestCTestXMLParser::test_parse_passed_test

# With coverage
pytest --cov=ci_harvester

# Verbose
pytest -v

# Stop on first failure
pytest -x
```

## Commit Message Format

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(parser): add support for CTest timeout status
fix(collector): handle Jenkins connection timeout
docs: update data model for measurements
test(api): add build endpoint integration tests
refactor(db): extract query helpers
```

## What NOT to Do

❌ Implement features without tests first
❌ Skip design doc review for significant changes
❌ Use raw SQL instead of SQLAlchemy ORM
❌ Ignore type hints
❌ Add dependencies without updating requirements.txt
❌ Commit directly to main branch
❌ Leave print statements in code (use structlog)

## Questions to Ask Yourself

Before implementing:
1. Did I write a failing test first?
2. Did I review the relevant design doc?
3. Does this change affect the data model?
4. Am I following existing code patterns?
5. Have I updated documentation?

## Getting Unstuck

1. **Check design docs** - Architecture decisions are documented
2. **Look at existing code** - Follow established patterns
3. **Run tests** - See what's expected
4. **Check models.py** - Understand the data model
5. **Read conftest.py** - See available test fixtures
