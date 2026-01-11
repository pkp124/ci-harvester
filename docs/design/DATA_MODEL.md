# CI Harvester - Data Model

## 1. Overview

This document defines the PostgreSQL database schema for CI Harvester. The schema is designed to:

- Store data from multiple CI platforms in a unified format
- Efficiently query test results across builds and time
- Support large-scale data with partitioning
- Maintain flexibility with JSONB metadata fields

## 2. Entity Relationship Diagram

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│   ci_sources    │       │      jobs       │       │     builds      │
├─────────────────┤       ├─────────────────┤       ├─────────────────┤
│ id (PK)         │──┐    │ id (PK)         │──┐    │ id (PK)         │
│ name            │  │    │ source_id (FK)  │  │    │ job_id (FK)     │
│ type            │  └───▶│ external_id     │  └───▶│ external_id     │
│ base_url        │       │ name            │       │ number          │
│ config          │       │ url             │       │ status          │
│ created_at      │       │ description     │       │ result          │
│ updated_at      │       │ is_active       │       │ started_at      │
└─────────────────┘       │ metadata        │       │ finished_at     │
                          │ created_at      │       │ duration_ms     │
                          │ updated_at      │       │ metadata        │
                          │ last_collected  │       │ created_at      │
                          └─────────────────┘       └────────┬────────┘
                                                             │
                          ┌──────────────────────────────────┼──────────────────────────────────┐
                          │                                  │                                  │
                          ▼                                  ▼                                  ▼
              ┌─────────────────┐               ┌─────────────────┐               ┌─────────────────┐
              │   build_logs    │               │  test_suites    │               │   artifacts     │
              ├─────────────────┤               ├─────────────────┤               ├─────────────────┤
              │ id (PK)         │               │ id (PK)         │               │ id (PK)         │
              │ build_id (FK)   │               │ build_id (FK)   │               │ build_id (FK)   │
              │ log_type        │               │ name            │               │ name            │
              │ content         │               │ framework       │               │ path            │
              │ size_bytes      │               │ total_tests     │               │ size_bytes      │
              │ created_at      │               │ passed          │               │ content_type    │
              └─────────────────┘               │ failed          │               │ stored_path     │
                                                │ skipped         │               │ metadata        │
                                                │ errors          │               │ created_at      │
                                                │ duration_ms     │               └─────────────────┘
                                                │ metadata        │
                                                │ created_at      │
                                                └────────┬────────┘
                                                         │
                                                         ▼
                                                ┌─────────────────┐
                                                │  test_results   │
                                                ├─────────────────┤
                                                │ id (PK)         │
                                                │ suite_id (FK)   │
                                                │ build_id (FK)   │
                                                │ name            │
                                                │ class_name      │
                                                │ status          │
                                                │ duration_ms     │
                                                │ message         │
                                                │ stack_trace     │
                                                │ stdout          │
                                                │ stderr          │
                                                │ metadata        │
                                                │ created_at      │
                                                └─────────────────┘
```

## 3. Table Definitions

### 3.1 ci_sources

Represents a CI platform instance (e.g., a specific Jenkins server).

```sql
CREATE TABLE ci_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL UNIQUE,
    type            VARCHAR(50) NOT NULL,  -- 'jenkins', 'github_actions', 'gitlab_ci'
    base_url        VARCHAR(2048) NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}',  -- Platform-specific config
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ci_sources_type ON ci_sources(type);
CREATE INDEX idx_ci_sources_active ON ci_sources(is_active) WHERE is_active = true;

COMMENT ON TABLE ci_sources IS 'CI platform instances to collect from';
COMMENT ON COLUMN ci_sources.config IS 'Platform-specific configuration (credentials stored separately)';
```

**Config JSONB Examples:**

```json
// Jenkins
{
  "job_filter": ".*-build$",
  "collect_artifacts": true,
  "max_builds_per_job": 100
}

// GitHub Actions
{
  "owner": "myorg",
  "repos": ["repo1", "repo2"],
  "workflow_filter": "ci.yml"
}
```

### 3.2 jobs

Represents a CI job/pipeline/workflow.

```sql
CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID NOT NULL REFERENCES ci_sources(id) ON DELETE CASCADE,
    external_id     VARCHAR(1024) NOT NULL,  -- Platform-specific job identifier
    name            VARCHAR(1024) NOT NULL,
    url             VARCHAR(2048),
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    last_collected  TIMESTAMP WITH TIME ZONE,
    
    CONSTRAINT uq_jobs_source_external UNIQUE (source_id, external_id)
);

CREATE INDEX idx_jobs_source ON jobs(source_id);
CREATE INDEX idx_jobs_active ON jobs(is_active) WHERE is_active = true;
CREATE INDEX idx_jobs_last_collected ON jobs(last_collected);
CREATE INDEX idx_jobs_name_gin ON jobs USING gin(name gin_trgm_ops);

COMMENT ON TABLE jobs IS 'CI jobs/pipelines discovered from sources';
COMMENT ON COLUMN jobs.external_id IS 'Platform-specific identifier (e.g., Jenkins job path)';
```

**Metadata JSONB Examples:**

```json
// Jenkins
{
  "full_name": "folder/subfolder/job-name",
  "job_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob",
  "buildable": true,
  "in_queue": false
}
```

### 3.3 builds

Represents a single build/run of a job.

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
    external_id     VARCHAR(255) NOT NULL,  -- Platform-specific build ID
    number          INTEGER NOT NULL,
    status          build_status NOT NULL DEFAULT 'unknown',
    result          build_result,
    started_at      TIMESTAMP WITH TIME ZONE,
    finished_at     TIMESTAMP WITH TIME ZONE,
    duration_ms     BIGINT,
    trigger_cause   VARCHAR(255),  -- 'manual', 'scm', 'timer', 'upstream'
    branch          VARCHAR(255),
    commit_sha      VARCHAR(64),
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    
    CONSTRAINT uq_builds_job_external UNIQUE (job_id, external_id)
);

CREATE INDEX idx_builds_job ON builds(job_id);
CREATE INDEX idx_builds_job_number ON builds(job_id, number DESC);
CREATE INDEX idx_builds_started ON builds(started_at DESC);
CREATE INDEX idx_builds_result ON builds(result);
CREATE INDEX idx_builds_branch ON builds(branch) WHERE branch IS NOT NULL;
CREATE INDEX idx_builds_commit ON builds(commit_sha) WHERE commit_sha IS NOT NULL;

-- Partial index for recent failed builds (common query)
CREATE INDEX idx_builds_recent_failures ON builds(started_at DESC) 
    WHERE result IN ('failure', 'unstable') AND started_at > NOW() - INTERVAL '30 days';

COMMENT ON TABLE builds IS 'Individual build runs of CI jobs';
```

**Metadata JSONB Examples:**

```json
// Jenkins
{
  "executor": "agent-01",
  "parameters": {
    "DEPLOY_ENV": "staging",
    "RUN_TESTS": "true"
  },
  "upstream_build": {
    "job": "trigger-job",
    "number": 42
  }
}
```

### 3.4 build_logs

Stores build console logs. Partitioned by month for efficient cleanup.

```sql
CREATE TABLE build_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    log_type        VARCHAR(50) NOT NULL DEFAULT 'console',  -- 'console', 'stage', 'step'
    stage_name      VARCHAR(255),  -- For pipeline stage logs
    content         TEXT NOT NULL,
    content_compressed BYTEA,  -- Optional: gzip compressed content
    size_bytes      INTEGER NOT NULL,
    line_count      INTEGER,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Create monthly partitions (automate with pg_partman or similar)
CREATE TABLE build_logs_2024_01 PARTITION OF build_logs
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE build_logs_2024_02 PARTITION OF build_logs
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
-- ... continue for each month

CREATE INDEX idx_build_logs_build ON build_logs(build_id);
CREATE INDEX idx_build_logs_type ON build_logs(log_type);

COMMENT ON TABLE build_logs IS 'Build console logs and stage outputs';
COMMENT ON COLUMN build_logs.content_compressed IS 'Gzip compressed content for large logs';
```

### 3.5 test_suites

Groups test results by suite (typically a test file or test class).

```sql
CREATE TYPE test_framework AS ENUM (
    'ctest',
    'junit',
    'pytest',
    'googletest',
    'catch2',
    'tap',
    'unknown'
);

CREATE TABLE test_suites (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    name            VARCHAR(1024) NOT NULL,
    framework       test_framework NOT NULL DEFAULT 'unknown',
    file_path       VARCHAR(2048),  -- Source file if available
    total_tests     INTEGER NOT NULL DEFAULT 0,
    passed          INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    skipped         INTEGER NOT NULL DEFAULT 0,
    errors          INTEGER NOT NULL DEFAULT 0,
    duration_ms     BIGINT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_test_suites_build ON test_suites(build_id);
CREATE INDEX idx_test_suites_framework ON test_suites(framework);
CREATE INDEX idx_test_suites_name ON test_suites(name);

COMMENT ON TABLE test_suites IS 'Test suite/file groupings within a build';
```

### 3.6 test_results

Individual test case results. Partitioned by month.

```sql
CREATE TYPE test_status AS ENUM (
    'passed',
    'failed',
    'skipped',
    'error',
    'timeout',
    'unknown'
);

CREATE TABLE test_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suite_id        UUID REFERENCES test_suites(id) ON DELETE CASCADE,
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    name            VARCHAR(1024) NOT NULL,
    class_name      VARCHAR(1024),
    full_name       VARCHAR(2048) GENERATED ALWAYS AS (
        CASE WHEN class_name IS NOT NULL 
             THEN class_name || '::' || name 
             ELSE name 
        END
    ) STORED,
    status          test_status NOT NULL,
    duration_ms     BIGINT,
    message         TEXT,  -- Failure/error message
    stack_trace     TEXT,  -- Full stack trace
    stdout          TEXT,  -- Captured stdout
    stderr          TEXT,  -- Captured stderr
    properties      JSONB NOT NULL DEFAULT '{}',  -- Test properties/attributes
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Create monthly partitions
CREATE TABLE test_results_2024_01 PARTITION OF test_results
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE test_results_2024_02 PARTITION OF test_results
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
-- ... continue for each month

CREATE INDEX idx_test_results_suite ON test_results(suite_id);
CREATE INDEX idx_test_results_build ON test_results(build_id);
CREATE INDEX idx_test_results_status ON test_results(status);
CREATE INDEX idx_test_results_name ON test_results(name);
CREATE INDEX idx_test_results_full_name ON test_results(full_name);
CREATE INDEX idx_test_results_failed ON test_results(build_id, created_at DESC) 
    WHERE status IN ('failed', 'error');

-- GIN index for searching test names
CREATE INDEX idx_test_results_name_gin ON test_results USING gin(name gin_trgm_ops);

COMMENT ON TABLE test_results IS 'Individual test case results';
COMMENT ON COLUMN test_results.properties IS 'Test-specific properties from the test framework';
```

### 3.7 artifacts

Stores metadata about build artifacts (not the artifacts themselves).

```sql
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    build_id        UUID NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    name            VARCHAR(1024) NOT NULL,
    path            VARCHAR(2048) NOT NULL,  -- Original path in CI
    size_bytes      BIGINT,
    content_type    VARCHAR(255),
    fingerprint     VARCHAR(64),  -- SHA-256 hash
    stored_path     VARCHAR(2048),  -- Local storage path (if downloaded)
    is_test_result  BOOLEAN NOT NULL DEFAULT false,  -- Parsed as test results
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_artifacts_build ON artifacts(build_id);
CREATE INDEX idx_artifacts_test_result ON artifacts(build_id) WHERE is_test_result = true;
CREATE INDEX idx_artifacts_name ON artifacts(name);

COMMENT ON TABLE artifacts IS 'Build artifact metadata and storage references';
```

### 3.8 collection_runs

Tracks harvesting runs for monitoring and debugging.

```sql
CREATE TYPE collection_status AS ENUM (
    'started',
    'completed',
    'failed',
    'partial'
);

CREATE TABLE collection_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID REFERENCES ci_sources(id) ON DELETE SET NULL,
    job_id          UUID REFERENCES jobs(id) ON DELETE SET NULL,
    run_type        VARCHAR(50) NOT NULL,  -- 'discover', 'collect', 'full'
    status          collection_status NOT NULL,
    started_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    finished_at     TIMESTAMP WITH TIME ZONE,
    builds_collected INTEGER DEFAULT 0,
    tests_collected  INTEGER DEFAULT 0,
    error_message   TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_collection_runs_source ON collection_runs(source_id);
CREATE INDEX idx_collection_runs_status ON collection_runs(status);
CREATE INDEX idx_collection_runs_started ON collection_runs(started_at DESC);

COMMENT ON TABLE collection_runs IS 'Audit log of harvesting operations';
```

## 4. Views

### 4.1 Recent Test Failures

```sql
CREATE VIEW v_recent_test_failures AS
SELECT 
    tr.id,
    tr.name AS test_name,
    tr.full_name,
    tr.status,
    tr.message,
    tr.duration_ms,
    b.number AS build_number,
    b.started_at AS build_started,
    j.name AS job_name,
    cs.name AS source_name
FROM test_results tr
JOIN builds b ON tr.build_id = b.id
JOIN jobs j ON b.job_id = j.id
JOIN ci_sources cs ON j.source_id = cs.id
WHERE tr.status IN ('failed', 'error')
  AND tr.created_at > NOW() - INTERVAL '7 days'
ORDER BY tr.created_at DESC;
```

### 4.2 Test Flakiness

```sql
CREATE VIEW v_test_flakiness AS
WITH test_history AS (
    SELECT 
        tr.full_name,
        j.id AS job_id,
        j.name AS job_name,
        COUNT(*) AS total_runs,
        COUNT(*) FILTER (WHERE tr.status = 'passed') AS passed_count,
        COUNT(*) FILTER (WHERE tr.status IN ('failed', 'error')) AS failed_count,
        COUNT(*) FILTER (WHERE tr.status = 'skipped') AS skipped_count
    FROM test_results tr
    JOIN builds b ON tr.build_id = b.id
    JOIN jobs j ON b.job_id = j.id
    WHERE tr.created_at > NOW() - INTERVAL '30 days'
    GROUP BY tr.full_name, j.id, j.name
)
SELECT 
    full_name,
    job_id,
    job_name,
    total_runs,
    passed_count,
    failed_count,
    ROUND(
        (failed_count::NUMERIC / NULLIF(passed_count + failed_count, 0)) * 100, 
        2
    ) AS failure_rate_pct,
    CASE 
        WHEN passed_count > 0 AND failed_count > 0 THEN true
        ELSE false
    END AS is_flaky
FROM test_history
WHERE total_runs >= 5  -- Minimum runs for significance
ORDER BY failure_rate_pct DESC;
```

### 4.3 Build Summary

```sql
CREATE VIEW v_build_summary AS
SELECT 
    b.id AS build_id,
    b.number,
    b.result,
    b.started_at,
    b.duration_ms,
    j.name AS job_name,
    cs.name AS source_name,
    COALESCE(SUM(ts.total_tests), 0) AS total_tests,
    COALESCE(SUM(ts.passed), 0) AS tests_passed,
    COALESCE(SUM(ts.failed), 0) AS tests_failed,
    COALESCE(SUM(ts.skipped), 0) AS tests_skipped,
    COALESCE(SUM(ts.errors), 0) AS tests_errors
FROM builds b
JOIN jobs j ON b.job_id = j.id
JOIN ci_sources cs ON j.source_id = cs.id
LEFT JOIN test_suites ts ON b.id = ts.build_id
GROUP BY b.id, b.number, b.result, b.started_at, b.duration_ms, j.name, cs.name;
```

## 5. Functions

### 5.1 Partition Management

```sql
-- Function to create monthly partitions
CREATE OR REPLACE FUNCTION create_monthly_partitions(
    table_name TEXT,
    start_date DATE,
    end_date DATE
) RETURNS void AS $$
DECLARE
    partition_date DATE := start_date;
    partition_name TEXT;
    partition_start TEXT;
    partition_end TEXT;
BEGIN
    WHILE partition_date < end_date LOOP
        partition_name := table_name || '_' || to_char(partition_date, 'YYYY_MM');
        partition_start := to_char(partition_date, 'YYYY-MM-DD');
        partition_end := to_char(partition_date + INTERVAL '1 month', 'YYYY-MM-DD');
        
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I
             FOR VALUES FROM (%L) TO (%L)',
            partition_name, table_name, partition_start, partition_end
        );
        
        partition_date := partition_date + INTERVAL '1 month';
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Usage: Create partitions for 2024
-- SELECT create_monthly_partitions('test_results', '2024-01-01', '2025-01-01');
```

### 5.2 Test History Lookup

```sql
-- Function to get test history
CREATE OR REPLACE FUNCTION get_test_history(
    p_test_name TEXT,
    p_job_id UUID DEFAULT NULL,
    p_limit INTEGER DEFAULT 100
) RETURNS TABLE (
    build_id UUID,
    build_number INTEGER,
    build_started TIMESTAMP WITH TIME ZONE,
    test_status test_status,
    duration_ms BIGINT,
    message TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        b.id,
        b.number,
        b.started_at,
        tr.status,
        tr.duration_ms,
        tr.message
    FROM test_results tr
    JOIN builds b ON tr.build_id = b.id
    WHERE tr.full_name = p_test_name
      AND (p_job_id IS NULL OR b.job_id = p_job_id)
    ORDER BY b.started_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
```

## 6. Indexes Strategy

### 6.1 Primary Query Patterns

| Query Pattern | Tables | Indexes |
|--------------|--------|---------|
| Get builds for job | builds | idx_builds_job, idx_builds_job_number |
| Get recent failures | test_results | idx_test_results_failed |
| Search test names | test_results | idx_test_results_name_gin |
| Get build logs | build_logs | idx_build_logs_build |
| Find flaky tests | test_results | idx_test_results_build, idx_test_results_status |

### 6.2 Index Maintenance

```sql
-- Reindex for performance (run during maintenance window)
REINDEX INDEX CONCURRENTLY idx_test_results_failed;

-- Check index usage
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
```

## 7. Data Retention

### 7.1 Retention Policy

| Data Type | Retention Period | Action |
|-----------|------------------|--------|
| Test Results | 1 year | Delete partitions |
| Build Logs | 90 days | Delete partitions |
| Builds | 2 years | Archive to cold storage |
| Jobs | Indefinite | Mark inactive |

### 7.2 Cleanup Procedure

```sql
-- Drop old partitions (run monthly)
DROP TABLE IF EXISTS test_results_2022_01;
DROP TABLE IF EXISTS build_logs_2022_01;

-- Archive old builds
INSERT INTO builds_archive SELECT * FROM builds WHERE started_at < NOW() - INTERVAL '2 years';
DELETE FROM builds WHERE started_at < NOW() - INTERVAL '2 years';
```

## 8. Performance Considerations

### 8.1 Table Sizes Estimates

| Table | Rows/Month | Size/Month | Notes |
|-------|------------|------------|-------|
| jobs | ~100 | < 1 MB | Grows slowly |
| builds | ~10,000 | ~10 MB | ~100 builds/job |
| build_logs | ~10,000 | ~1 GB | Depends on log size |
| test_suites | ~50,000 | ~50 MB | ~5 suites/build |
| test_results | ~500,000 | ~500 MB | ~50 tests/suite |

### 8.2 Optimization Tips

1. **Connection Pooling**: Use PgBouncer in production
2. **VACUUM**: Schedule regular VACUUM ANALYZE
3. **Partitioning**: Manage partitions with pg_partman
4. **Read Replicas**: Use replicas for API reads
5. **Compression**: Enable TOAST compression for text fields

## 9. Migration Notes

Initial migration script order:
1. Enable required extensions (pg_trgm, uuid-ossp)
2. Create ENUMs
3. Create tables (order matters for FKs)
4. Create indexes
5. Create views
6. Create functions
7. Create initial partitions
