# Contributing to CI Harvester

Thank you for your interest in contributing to CI Harvester! This document provides guidelines and best practices for contributing to the project.

## Table of Contents

- [Development Philosophy](#development-philosophy)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Test-Driven Development](#test-driven-development)
- [Code Style](#code-style)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)

## Development Philosophy

### Core Principles

1. **Test-Driven Development (TDD)**: Write tests before implementation
2. **Design First**: Review/update design docs before major changes
3. **Keep It Simple**: Avoid over-engineering; solve the current problem
4. **Document As You Go**: Update docs alongside code changes

### Architecture Guidelines

- Follow the established data model hierarchy (Products → Jobs → Builds)
- Keep collectors, parsers, and database logic separated
- Use dependency injection for testability
- Prefer composition over inheritance

## Getting Started

### Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Docker & Docker Compose (for development environment)

### Development Setup

```bash
# Clone the repository
git clone <repository-url>
cd ci-harvester

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Set up pre-commit hooks
pre-commit install

# Copy environment template
cp .env.example .env
# Edit .env with your settings

# Start development services
docker-compose -f docker/docker-compose.yml up -d postgres-data

# Run tests to verify setup
pytest
```

### Project Structure

```
ci-harvester/
├── ci_harvester/           # Main package
│   ├── collectors/         # CI platform integrations
│   ├── parsers/            # Test result parsers
│   ├── db/                 # Database models and operations
│   ├── api/                # REST API
│   └── utils/              # Shared utilities
├── dags/                   # Airflow DAG definitions
├── tests/                  # Test suite (mirrors source structure)
├── docs/
│   └── design/             # Design documentation
└── docker/                 # Docker configurations
```

## Development Workflow

### 1. Understand the Task

Before coding:

1. **Check existing design docs** in `docs/design/`
2. **Understand the data model** in `docs/design/DATA_MODEL.md`
3. **Review related code** to understand existing patterns
4. **Ask questions** if requirements are unclear

### 2. Create a Branch

```bash
# Feature branch
git checkout -b feat/add-github-actions-collector

# Bug fix branch
git checkout -b fix/ctest-parser-timeout-handling

# Documentation branch
git checkout -b docs/update-api-design
```

### 3. Follow TDD Cycle

See [Test-Driven Development](#test-driven-development) section below.

### 4. Commit Changes

Use [Conventional Commits](https://www.conventionalcommits.org/):

```bash
# Feature
git commit -m "feat(collectors): add GitHub Actions collector"

# Bug fix
git commit -m "fix(parser): handle CTest timeout status correctly"

# Documentation
git commit -m "docs: update API design for test endpoints"

# Tests
git commit -m "test(collectors): add Jenkins folder discovery tests"

# Refactoring
git commit -m "refactor(db): extract common query patterns"
```

### 5. Submit Pull Request

See [Pull Request Process](#pull-request-process) section.

## Test-Driven Development

### The TDD Cycle

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   ┌─────────┐      ┌─────────┐      ┌──────────────┐       │
│   │  RED    │ ───▶ │  GREEN  │ ───▶ │   REFACTOR   │ ──┐   │
│   │  Write  │      │  Make   │      │   Clean up   │   │   │
│   │  Test   │      │  Pass   │      │   the code   │   │   │
│   └─────────┘      └─────────┘      └──────────────┘   │   │
│        ▲                                               │   │
│        └───────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### TDD Example

**Task**: Add support for parsing CTest timeout status

**Step 1: RED - Write a failing test**

```python
# tests/parsers/test_ctest.py

def test_parse_timeout_status(self, parser):
    """Test parsing a timed-out test."""
    xml = b'''<?xml version="1.0"?>
    <Site><Testing>
        <Test Status="timeout">
            <Name>SlowTest::test_forever</Name>
            <Results>
                <NamedMeasurement name="Execution Time" type="numeric/double">
                    <Value>300.0</Value>
                </NamedMeasurement>
            </Results>
        </Test>
    </Testing></Site>'''
    
    report = parser.parse(xml)
    
    assert len(report.tests) == 1
    assert report.tests[0].status == TestStatus.TIMEOUT
    assert report.tests[0].duration_seconds == 300.0
```

Run the test to see it fail:
```bash
pytest tests/parsers/test_ctest.py::TestCTestXMLParser::test_parse_timeout_status -v
```

**Step 2: GREEN - Make the test pass**

```python
# ci_harvester/parsers/ctest.py

def _map_status(self, status_str: str) -> TestStatus:
    status_map = {
        'passed': TestStatus.PASSED,
        'failed': TestStatus.FAILED,
        'timeout': TestStatus.TIMEOUT,  # Add this line
        # ...
    }
    return status_map.get(status_str.lower(), TestStatus.ERROR)
```

Run the test again to see it pass:
```bash
pytest tests/parsers/test_ctest.py::TestCTestXMLParser::test_parse_timeout_status -v
```

**Step 3: REFACTOR - Clean up if needed**

Review the code for any improvements, run all tests:
```bash
pytest
```

### Test Organization

```
tests/
├── conftest.py              # Shared fixtures
├── collectors/
│   ├── __init__.py
│   ├── test_jenkins.py      # Jenkins collector tests
│   └── test_github.py       # GitHub Actions collector tests
├── parsers/
│   ├── __init__.py
│   ├── test_ctest.py        # CTest parser tests
│   └── fixtures/            # Sample XML files
│       ├── ctest_passed.xml
│       └── ctest_failed.xml
├── db/
│   ├── __init__.py
│   └── test_models.py       # Database model tests
└── api/
    ├── __init__.py
    └── test_builds.py       # API endpoint tests
```

### Test Categories

```python
# Unit test - fast, isolated
def test_parse_test_name_components():
    name, class_name, suite = parser._parse_test_name("Suite::Class::test")
    assert name == "test"

# Integration test - involves database
@pytest.mark.integration
def test_save_creates_test_executions(db_session, sample_build):
    saver = CTestResultSaver(db_session)
    stats = saver.save(report, sample_build)
    assert stats['executions_created'] == 3

# Slow test - mark for optional exclusion
@pytest.mark.slow
def test_process_large_xml_file():
    ...
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ci_harvester --cov-report=html

# Run specific test file
pytest tests/parsers/test_ctest.py

# Run specific test
pytest tests/parsers/test_ctest.py::TestCTestXMLParser::test_parse_passed_test

# Skip slow tests
pytest -m "not slow"

# Run only integration tests
pytest -m integration

# Verbose output
pytest -v

# Stop on first failure
pytest -x
```

### Coverage Requirements

- **New code**: Minimum 80% coverage
- **Critical paths** (parsers, DB operations): 90%+ coverage
- **Run coverage check**: `pytest --cov=ci_harvester --cov-fail-under=80`

## Code Style

### Formatting Tools

```bash
# Format code with black
black ci_harvester tests

# Lint with ruff
ruff check ci_harvester tests

# Type check with mypy
mypy ci_harvester
```

### Style Guidelines

```python
# Use type hints
from typing import List, Optional, Dict
from uuid import UUID

def get_test_history(
    test_id: UUID,
    limit: int = 100,
    include_passed: bool = True
) -> List[TestExecution]:
    ...

# Use dataclasses for data structures
from dataclasses import dataclass, field

@dataclass
class ParseResult:
    tests: List[TestResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

# Document public APIs
def calculate_flakiness(test_id: UUID, days: int = 30) -> float:
    """
    Calculate test flakiness score.
    
    Flakiness is defined as the ratio of inconsistent results
    (pass after fail or fail after pass) to total runs.
    
    Args:
        test_id: UUID of the test definition
        days: Number of days to analyze (default: 30)
        
    Returns:
        Flakiness score between 0.0 (stable) and 1.0 (completely flaky)
        
    Raises:
        ValueError: If test_id doesn't exist
    """

# Use constants for magic values
MAX_BUILDS_PER_COLLECTION = 100
DEFAULT_RETENTION_DAYS = 365
CTEST_TIMEOUT_SECONDS = 300

# Prefer explicit over implicit
# Good
if build.result == BuildResult.FAILURE:
    
# Avoid
if not build.result:
```

### Import Organization

```python
# Standard library
import os
from datetime import datetime
from typing import List, Optional

# Third-party
import structlog
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

# Local imports
from ci_harvester.db import get_session
from ci_harvester.db.models import Build, TestExecution
from ci_harvester.parsers.ctest import CTestXMLParser
```

## Documentation

### When to Update Docs

- **New feature**: Update or create design doc
- **API change**: Update `docs/design/API_DESIGN.md`
- **Schema change**: Update `docs/design/DATA_MODEL.md`
- **New integration**: Create `docs/design/{INTEGRATION}.md`

### Documentation Structure

```markdown
# Feature Name

## Overview
Brief description of what this does.

## Design
How it works, architecture decisions.

## Usage
Code examples, configuration.

## API Reference
If applicable, endpoint documentation.
```

### Docstring Format

```python
def complex_function(
    param1: str,
    param2: int,
    optional_param: bool = False
) -> Dict[str, Any]:
    """
    Brief description of the function.
    
    Longer description if needed, explaining the purpose,
    behavior, and any important details.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        optional_param: Description with default noted
        
    Returns:
        Description of return value, including structure
        if returning a dict/complex type.
        
    Raises:
        ValueError: When param1 is empty
        ConnectionError: When unable to reach external service
        
    Example:
        >>> result = complex_function("test", 42)
        >>> print(result['status'])
        'success'
    """
```

## Pull Request Process

### Before Submitting

- [ ] All tests pass locally (`pytest`)
- [ ] Code is formatted (`black`, `ruff`)
- [ ] Type hints are included
- [ ] Docstrings are updated
- [ ] Design docs are updated (if applicable)
- [ ] Commit messages follow conventional commits

### PR Template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] All tests passing

## Documentation
- [ ] Docstrings updated
- [ ] Design docs updated
- [ ] README updated (if applicable)

## Related Issues
Closes #123
```

### Review Checklist

Reviewers will check:

1. **Tests**: Are there tests? Do they follow TDD?
2. **Design**: Does it fit the architecture?
3. **Code Quality**: Style, types, documentation
4. **Performance**: Any obvious bottlenecks?
5. **Security**: Any sensitive data handling?

## Getting Help

- **Questions**: Open a discussion or issue
- **Bugs**: Open an issue with reproduction steps
- **Feature Ideas**: Open an issue for discussion first

Thank you for contributing! 🎉
