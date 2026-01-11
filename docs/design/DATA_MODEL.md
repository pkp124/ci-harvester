# CI Harvester - Data Model

## 1. Overview

This document defines the PostgreSQL database schema for CI Harvester. The schema is designed around the following hierarchy:

- **Products** - Top-level grouping (e.g., software products, projects)
- **Jobs** - CI jobs belonging to a product
- **Builds** - Individual build runs of a job
- **Tests** - Test definitions belonging to a job (persistent across builds)
- **Test Executions** - Execution of a test in a specific build
- **CTest Measurements** - Measurements captured during test execution

## 2. Entity Relationship Diagram

```
┌─────────────────┐
│    products     │
├─────────────────┤
│ id (PK)         │
│ name            │
│ description     │
│ metadata        │
│ created_at      │
│ updated_at      │
└────────┬────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐
│      jobs       │
├─────────────────┤
│ id (PK)         │
│ product_id (FK) │──────────────────────────────────┐
│ external_id     │                                  │
│ name            │                                  │
│ url             │                                  │
│ ci_source       │                                  │
│ is_active       │                                  │
│ metadata        │                                  │
│ created_at      │                                  │
│ updated_at      │                                  │
│ last_collected  │                                  │
└────────┬────────┘                                  │
         │                                           │
         │ 1:N                                       │ 1:N
         ▼                                           ▼
┌─────────────────┐                        ┌─────────────────┐
│     builds      │                        │      tests      │
├─────────────────┤                        ├─────────────────┤
│ id (PK)         │                        │ id (PK)         │
│ job_id (FK)     │                        │ job_id (FK)     │
│ external_id     │                        │ name            │
│ number          │                        │ full_name       │
│ status          │                        │ class_name      │
│ result          │                        │ file_path       │
│ started_at      │                        │ is_active       │
│ finished_at     │                        │ metadata        │
│ duration_ms     │                        │ created_at      │
│ branch          │                        │ updated_at      │
│ commit_sha      │                        └────────┬────────┘
│ metadata        │                                 │
│ created_at      │                                 │
└────────┬────────┘                                 │
         │                                          │
         │ 1:N                                      │
         ▼                                          │
┌─────────────────┐                                 │
│ test_executions │◄────────────────────────────────┘
├─────────────────┤           N:1
│ id (PK)         │
│ build_id (FK)   │
│ test_id (FK)    │
│ status          │
│ duration_ms     │
│ message         │
│ stdout          │
│ stderr          │
│ metadata        │
│ created_at      │
└────────┬────────┘
         │
         │ 1:N
         ▼
┌─────────────────────┐
│  ctest_measurements │
├─────────────────────┤
│ id (PK)             │
│ test_execution_id   │
│ name                │
│ type                │
│ value               │
│ unit                │
│ created_at          │
└─────────────────────┘


Additional Tables:
┌─────────────────┐       ┌─────────────────┐
│   build_logs    │       │   artifacts     │
├─────────────────┤       ├─────────────────┤
│ id (PK)         │       │ id (PK)         │
│ build_id (FK)   │       │ build_id (FK)   │
│ log_type        │       │ name            │
│ content         │       │ path            │
│ size_bytes      │       │ size_bytes      │
│ created_at      │       │ content_type    │
└─────────────────┘       │ is_test_result  │
                          │ metadata        │
                          │ created_at      │
                          └─────────────────┘
```

## 3. Table Definitions

### 3.1 products

Top-level grouping for organizing CI jobs by product or project.

```sql
CREATE TABLE products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL UNIQUE,
    description     TEXT,
    repository_url  VARCHAR(2048),
    metadata        JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_products_name ON products(name);
CREATE INDEX idx_products_active ON products(is_active) WHERE is_active = true;

COMMENT ON TABLE products IS 'Top-level product/project grouping';
```

**Example:**

```json
{
  "id": "uuid",
  "name": "MyProduct",
  "description": "Core product build and test pipeline",
  "repository_url": "https://github.com/org/myproduct",
  "metadata": {
    "team": "platform",
    "tier": "critical"
  }
}
```

### 3.2 jobs

CI jobs belonging to a product.

```sql
CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    external_id     VARCHAR(1024) NOT NULL,  -- CI platform job identifier
    name            VARCHAR(1024) NOT NULL,
    url             VARCHAR(2048),
    ci_source       VARCHAR(50) NOT NULL,    -- 'jenkins', 'github_actions', etc.
    ci_source_url   VARCHAR(2048),           -- Base URL of CI server
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_collected  TIMESTAMP WITH TIME ZONE,
    
    CONSTRAINT uq_jobs_product_external UNIQUE (product_id, external_id)
);

CREATE INDEX idx_jobs_product ON jobs(product_id);
CREATE INDEX idx_jobs_ci_source ON jobs(ci_source);
CREATE INDEX idx_jobs_active ON jobs(is_active) WHERE is_active = true;
CREATE INDEX idx_jobs_last_collected ON jobs(last_collected);

COMMENT ON TABLE jobs IS 'CI jobs/pipelines belonging to a product';
COMMENT ON COLUMN jobs.external_id IS 'CI platform identifier (e.g., Jenkins job path)';
COMMENT ON COLUMN jobs.ci_source IS 'Type of CI system: jenkins, github_actions, gitlab_ci';
```

**Metadata Examples:**

```json
// Jenkins job
{
  "full_name": "folder/subfolder/job-name",
  "job_class": "WorkflowJob",
  "jenkinsfile_path": "Jenkinsfile"
}

// GitHub Actions
{
  "workflow_file": ".github/workflows/ci.yml",
  "triggers": ["push", "pull_request"]
}
```

### 3.3 builds

Individual build runs of a job.

```sql
CREATE TYPE build_status AS ENUM (
    'pending',
    'running',
    'completed',
    'aborted',
    'unknown'
);

CREATE TYPE build_result AS ENUM (
    'success',
    'failure',
    'unstable',
    'aborted',
    'not_built',
    'unknown'
);

CREATE TABLE builds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    external_id     VARCHAR(255) NOT NULL,
    number          INTEGER NOT NULL,
    status          build_status NOT NULL DEFAULT 'unknown',
    result          build_result,
    started_at      TIMESTAMP WITH TIME ZONE,
    finished_at     TIMESTAMP WITH TIME ZONE,
    duration_ms     BIGINT,
    trigger_cause   VARCHAR(255),
    branch          VARCHAR(255),
    commit_sha      VARCHAR(64),
    commit_message  TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT uq_builds_job_number UNIQUE (job_id, number)
);

CREATE INDEX idx_builds_job ON builds(job_id);
CREATE INDEX idx_builds_job_number ON builds(job_id, number DESC);
CREATE INDEX idx_builds_started ON builds(started_at DESC);
CREATE INDEX idx_builds_result ON builds(result);
CREATE INDEX idx_builds_branch ON builds(branch) WHERE branch IS NOT NULL;
CREATE INDEX idx_builds_commit ON builds(commit_sha) WHERE commit_sha IS NOT NULL;

-- Partial index for recent failed builds
CREATE INDEX idx_builds_recent_failures ON builds(started_at DESC) 
    WHERE result IN ('failure', 'unstable') AND started_at > NOW() - INTERVAL '30 days';

COMMENT ON TABLE builds IS 'Individual build runs of CI jobs';
```

### 3.4 tests

Test definitions belonging to a job. These represent the test cases themselves, not individual executions.

```sql
CREATE TABLE tests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    name            VARCHAR(1024) NOT NULL,
    full_name       VARCHAR(2048) NOT NULL,  -- Includes class/suite name
    class_name      VARCHAR(1024),
    suite_name      VARCHAR(1024),
    file_path       VARCHAR(2048),
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    first_seen_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT uq_tests_job_fullname UNIQUE (job_id, full_name)
);

CREATE INDEX idx_tests_job ON tests(job_id);
CREATE INDEX idx_tests_name ON tests(name);
CREATE INDEX idx_tests_full_name ON tests(full_name);
CREATE INDEX idx_tests_class ON tests(class_name) WHERE class_name IS NOT NULL;
CREATE INDEX idx_tests_suite ON tests(suite_name) WHERE suite_name IS NOT NULL;
CREATE INDEX idx_tests_active ON tests(is_active) WHERE is_active = true;

-- GIN index for text search
CREATE INDEX idx_tests_full_name_gin ON tests USING gin(full_name gin_trgm_ops);

COMMENT ON TABLE tests IS 'Test definitions/cases belonging to a job';
COMMENT ON COLUMN tests.full_name IS 'Fully qualified test name (e.g., TestSuite::TestClass::test_method)';
```

**Example:**

```json
{
  "id": "uuid",
  "job_id": "uuid",
  "name": "test_addition",
  "full_name": "MathTests::ArithmeticSuite::test_addition",
  "class_name": "ArithmeticSuite",
  "suite_name": "MathTests",
  "file_path": "tests/math/test_arithmetic.cpp",
  "metadata": {
    "labels": ["unit", "fast"],
    "timeout_seconds": 60
  }
}
```

### 3.5 test_executions

Execution of a test in a specific build.

```sql
CREATE TYPE test_status AS ENUM (
    'passed',
    'failed',
    'skipped',
    'error',
    'timeout',
    'not_run',
    'unknown'
);

CREATE TABLE test_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    test_id         UUID NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    status          test_status NOT NULL,
    duration_ms     BIGINT,
    message         TEXT,              -- Failure/error message
    stack_trace     TEXT,
    stdout          TEXT,
    stderr          TEXT,
    command_line    TEXT,
    exit_code       INTEGER,
    retry_count     INTEGER DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT uq_test_executions_build_test UNIQUE (build_id, test_id)
);

CREATE INDEX idx_test_executions_build ON test_executions(build_id);
CREATE INDEX idx_test_executions_test ON test_executions(test_id);
CREATE INDEX idx_test_executions_status ON test_executions(status);
CREATE INDEX idx_test_executions_failed ON test_executions(build_id, created_at DESC) 
    WHERE status IN ('failed', 'error');

-- Composite index for common query patterns
CREATE INDEX idx_test_executions_test_status ON test_executions(test_id, status, created_at DESC);

COMMENT ON TABLE test_executions IS 'Individual test execution within a build';
```

### 3.6 ctest_measurements

CTest measurements captured during test execution.

```sql
CREATE TABLE ctest_measurements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_execution_id   UUID NOT NULL REFERENCES test_executions(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    type                VARCHAR(50) NOT NULL,   -- 'numeric/double', 'text/string', etc.
    value_numeric       DOUBLE PRECISION,
    value_text          TEXT,
    unit                VARCHAR(50),            -- 'seconds', 'bytes', 'percent', etc.
    created_at          TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ctest_measurements_execution ON ctest_measurements(test_execution_id);
CREATE INDEX idx_ctest_measurements_name ON ctest_measurements(name);
CREATE INDEX idx_ctest_measurements_type ON ctest_measurements(type);

-- Index for numeric measurements (common for performance analysis)
CREATE INDEX idx_ctest_measurements_numeric ON ctest_measurements(name, value_numeric) 
    WHERE value_numeric IS NOT NULL;

COMMENT ON TABLE ctest_measurements IS 'CTest measurements from test executions';
COMMENT ON COLUMN ctest_measurements.type IS 'CTest measurement type: numeric/double, text/string, etc.';
```

**Common CTest Measurements:**

| Name | Type | Unit | Description |
|------|------|------|-------------|
| Execution Time | numeric/double | seconds | Test duration |
| Processors | numeric/double | - | Number of processors used |
| Exit Code | numeric/double | - | Process exit code |
| Exit Value | text/string | - | Exit value description |
| Completion Status | text/string | - | Completed, Timeout, etc. |
| Memory Usage | numeric/double | bytes | Peak memory usage |

### 3.7 build_logs

Build console logs.

```sql
CREATE TABLE build_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    log_type        VARCHAR(50) NOT NULL DEFAULT 'console',
    stage_name      VARCHAR(255),
    content         TEXT NOT NULL,
    content_compressed BYTEA,
    size_bytes      INTEGER NOT NULL,
    line_count      INTEGER,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_build_logs_build ON build_logs(build_id);
CREATE INDEX idx_build_logs_type ON build_logs(log_type);

COMMENT ON TABLE build_logs IS 'Build console logs and stage outputs';
```

### 3.8 artifacts

Build artifacts metadata.

```sql
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    name            VARCHAR(1024) NOT NULL,
    path            VARCHAR(2048) NOT NULL,
    size_bytes      BIGINT,
    content_type    VARCHAR(255),
    fingerprint     VARCHAR(64),
    stored_path     VARCHAR(2048),
    is_test_result  BOOLEAN NOT NULL DEFAULT false,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_artifacts_build ON artifacts(build_id);
CREATE INDEX idx_artifacts_test_result ON artifacts(build_id) WHERE is_test_result = true;

COMMENT ON TABLE artifacts IS 'Build artifact metadata and storage references';
```

## 4. Views

### 4.1 Test Summary per Build

```sql
CREATE VIEW v_build_test_summary AS
SELECT 
    b.id AS build_id,
    b.number AS build_number,
    b.result AS build_result,
    b.started_at,
    j.id AS job_id,
    j.name AS job_name,
    p.id AS product_id,
    p.name AS product_name,
    COUNT(te.id) AS total_tests,
    COUNT(te.id) FILTER (WHERE te.status = 'passed') AS passed,
    COUNT(te.id) FILTER (WHERE te.status = 'failed') AS failed,
    COUNT(te.id) FILTER (WHERE te.status = 'skipped') AS skipped,
    COUNT(te.id) FILTER (WHERE te.status = 'error') AS errors,
    COALESCE(SUM(te.duration_ms), 0) AS total_duration_ms,
    ROUND(
        COUNT(te.id) FILTER (WHERE te.status = 'passed')::NUMERIC / 
        NULLIF(COUNT(te.id) FILTER (WHERE te.status IN ('passed', 'failed', 'error')), 0) * 100,
        2
    ) AS pass_rate_pct
FROM builds b
JOIN jobs j ON b.job_id = j.id
JOIN products p ON j.product_id = p.id
LEFT JOIN test_executions te ON b.id = te.build_id
GROUP BY b.id, b.number, b.result, b.started_at, j.id, j.name, p.id, p.name;
```

### 4.2 Test Flakiness Analysis

```sql
CREATE VIEW v_test_flakiness AS
WITH test_history AS (
    SELECT 
        t.id AS test_id,
        t.full_name,
        t.name,
        j.id AS job_id,
        j.name AS job_name,
        p.name AS product_name,
        COUNT(te.id) AS total_runs,
        COUNT(te.id) FILTER (WHERE te.status = 'passed') AS passed_count,
        COUNT(te.id) FILTER (WHERE te.status IN ('failed', 'error')) AS failed_count,
        COUNT(te.id) FILTER (WHERE te.status = 'skipped') AS skipped_count,
        AVG(te.duration_ms) FILTER (WHERE te.status = 'passed') AS avg_duration_ms
    FROM tests t
    JOIN jobs j ON t.job_id = j.id
    JOIN products p ON j.product_id = p.id
    LEFT JOIN test_executions te ON t.id = te.test_id
    LEFT JOIN builds b ON te.build_id = b.id
    WHERE b.created_at > NOW() - INTERVAL '30 days'
    GROUP BY t.id, t.full_name, t.name, j.id, j.name, p.name
)
SELECT 
    test_id,
    full_name,
    name,
    job_id,
    job_name,
    product_name,
    total_runs,
    passed_count,
    failed_count,
    ROUND(
        (failed_count::NUMERIC / NULLIF(passed_count + failed_count, 0)) * 100, 
        2
    ) AS failure_rate_pct,
    ROUND(avg_duration_ms::NUMERIC, 2) AS avg_duration_ms,
    CASE 
        WHEN passed_count > 0 AND failed_count > 0 THEN true
        ELSE false
    END AS is_flaky
FROM test_history
WHERE total_runs >= 5
ORDER BY failure_rate_pct DESC NULLS LAST;
```

### 4.3 Recent Test Failures

```sql
CREATE VIEW v_recent_test_failures AS
SELECT 
    te.id AS execution_id,
    t.full_name AS test_name,
    t.class_name,
    t.suite_name,
    te.status,
    te.message,
    te.duration_ms,
    b.number AS build_number,
    b.started_at AS build_started,
    b.branch,
    b.commit_sha,
    j.name AS job_name,
    p.name AS product_name
FROM test_executions te
JOIN tests t ON te.test_id = t.id
JOIN builds b ON te.build_id = b.id
JOIN jobs j ON b.job_id = j.id
JOIN products p ON j.product_id = p.id
WHERE te.status IN ('failed', 'error')
  AND te.created_at > NOW() - INTERVAL '7 days'
ORDER BY te.created_at DESC;
```

### 4.4 Test Performance Trends

```sql
CREATE VIEW v_test_performance AS
SELECT 
    t.id AS test_id,
    t.full_name,
    j.name AS job_name,
    p.name AS product_name,
    DATE_TRUNC('day', b.started_at) AS date,
    COUNT(te.id) AS executions,
    AVG(te.duration_ms) AS avg_duration_ms,
    MIN(te.duration_ms) AS min_duration_ms,
    MAX(te.duration_ms) AS max_duration_ms,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY te.duration_ms) AS p50_duration_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY te.duration_ms) AS p95_duration_ms
FROM tests t
JOIN jobs j ON t.job_id = j.id
JOIN products p ON j.product_id = p.id
JOIN test_executions te ON t.id = te.test_id
JOIN builds b ON te.build_id = b.id
WHERE te.status = 'passed'
  AND b.started_at > NOW() - INTERVAL '30 days'
GROUP BY t.id, t.full_name, j.name, p.name, DATE_TRUNC('day', b.started_at)
ORDER BY date DESC;
```

## 5. Functions

### 5.1 Get or Create Test

```sql
CREATE OR REPLACE FUNCTION get_or_create_test(
    p_job_id UUID,
    p_name VARCHAR(1024),
    p_full_name VARCHAR(2048),
    p_class_name VARCHAR(1024) DEFAULT NULL,
    p_suite_name VARCHAR(1024) DEFAULT NULL,
    p_file_path VARCHAR(2048) DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_test_id UUID;
BEGIN
    -- Try to find existing test
    SELECT id INTO v_test_id
    FROM tests
    WHERE job_id = p_job_id AND full_name = p_full_name;
    
    IF v_test_id IS NOT NULL THEN
        -- Update last_seen_at
        UPDATE tests SET 
            last_seen_at = NOW(),
            is_active = true,
            updated_at = NOW()
        WHERE id = v_test_id;
        RETURN v_test_id;
    END IF;
    
    -- Create new test
    INSERT INTO tests (job_id, name, full_name, class_name, suite_name, file_path)
    VALUES (p_job_id, p_name, p_full_name, p_class_name, p_suite_name, p_file_path)
    RETURNING id INTO v_test_id;
    
    RETURN v_test_id;
END;
$$ LANGUAGE plpgsql;
```

### 5.2 Get Test History

```sql
CREATE OR REPLACE FUNCTION get_test_history(
    p_test_id UUID,
    p_limit INTEGER DEFAULT 100
) RETURNS TABLE (
    build_id UUID,
    build_number INTEGER,
    build_started TIMESTAMP WITH TIME ZONE,
    status test_status,
    duration_ms BIGINT,
    message TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        b.id,
        b.number,
        b.started_at,
        te.status,
        te.duration_ms,
        te.message
    FROM test_executions te
    JOIN builds b ON te.build_id = b.id
    WHERE te.test_id = p_test_id
    ORDER BY b.started_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
```

### 5.3 Get CTest Measurement Stats

```sql
CREATE OR REPLACE FUNCTION get_measurement_stats(
    p_test_id UUID,
    p_measurement_name VARCHAR(255),
    p_days INTEGER DEFAULT 30
) RETURNS TABLE (
    min_value DOUBLE PRECISION,
    max_value DOUBLE PRECISION,
    avg_value DOUBLE PRECISION,
    p50_value DOUBLE PRECISION,
    p95_value DOUBLE PRECISION,
    sample_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        MIN(cm.value_numeric),
        MAX(cm.value_numeric),
        AVG(cm.value_numeric),
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cm.value_numeric),
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cm.value_numeric),
        COUNT(*)
    FROM ctest_measurements cm
    JOIN test_executions te ON cm.test_execution_id = te.id
    JOIN builds b ON te.build_id = b.id
    WHERE te.test_id = p_test_id
      AND cm.name = p_measurement_name
      AND cm.value_numeric IS NOT NULL
      AND b.started_at > NOW() - (p_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;
```

## 6. Sample Data Flow

### 6.1 Ingestion Flow

```
1. Create/Get Product
   └─> INSERT INTO products (name) VALUES ('MyProduct')

2. Create/Get Job
   └─> INSERT INTO jobs (product_id, external_id, name, ci_source)
       VALUES (product_id, 'folder/my-build-job', 'my-build-job', 'jenkins')

3. Create Build
   └─> INSERT INTO builds (job_id, number, status, result, started_at)
       VALUES (job_id, 142, 'completed', 'success', '2024-01-15 12:00:00')

4. For each test in CTest results:
   a. Get or Create Test
      └─> SELECT get_or_create_test(job_id, 'test_add', 'Math::Arithmetic::test_add', ...)
   
   b. Create Test Execution
      └─> INSERT INTO test_executions (build_id, test_id, status, duration_ms)
          VALUES (build_id, test_id, 'passed', 123)
   
   c. Create CTest Measurements
      └─> INSERT INTO ctest_measurements (test_execution_id, name, type, value_numeric, unit)
          VALUES (exec_id, 'Execution Time', 'numeric/double', 0.123, 'seconds')
```

## 7. Indexes Strategy

### 7.1 Primary Query Patterns

| Query Pattern | Tables | Indexes |
|--------------|--------|---------|
| Get builds for job | builds | idx_builds_job, idx_builds_job_number |
| Get test executions for build | test_executions | idx_test_executions_build |
| Get test history | test_executions | idx_test_executions_test |
| Find failing tests | test_executions | idx_test_executions_failed |
| Search tests by name | tests | idx_tests_full_name_gin |
| Get measurements for test | ctest_measurements | idx_ctest_measurements_execution |
| Analyze measurement trends | ctest_measurements | idx_ctest_measurements_numeric |

## 8. Data Retention

| Data Type | Retention Period | Action |
|-----------|------------------|--------|
| test_executions | 1 year | Archive/Delete |
| ctest_measurements | 1 year | Delete with parent |
| build_logs | 90 days | Delete |
| builds | 2 years | Archive |
| tests | Indefinite | Mark inactive |
| jobs | Indefinite | Mark inactive |
| products | Indefinite | Mark inactive |

## 9. Migration Script

```sql
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create types
CREATE TYPE build_status AS ENUM ('pending', 'running', 'completed', 'aborted', 'unknown');
CREATE TYPE build_result AS ENUM ('success', 'failure', 'unstable', 'aborted', 'not_built', 'unknown');
CREATE TYPE test_status AS ENUM ('passed', 'failed', 'skipped', 'error', 'timeout', 'not_run', 'unknown');

-- Create tables in order (see definitions above)
-- 1. products
-- 2. jobs
-- 3. builds
-- 4. tests
-- 5. test_executions
-- 6. ctest_measurements
-- 7. build_logs
-- 8. artifacts

-- Create views
-- Create functions
```
