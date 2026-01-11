# CI Harvester - Scheduling Policy

## 1. Overview

This document defines the scheduling policy for CI Harvester. **Apache Airflow is the scheduling engine** - it handles DAG scheduling, task execution, retries, and worker management.

Our scheduling module provides:
- **Configuration** - User-configurable settings that Airflow DAGs read
- **Job Prioritization** - Which jobs to collect first when a DAG runs
- **Rate Limiting** - Throttling requests to CI platforms
- **Backpressure Detection** - Monitoring system load

## 2. Architecture: Airflow + Configuration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Airflow Scheduler                               │
│                    (Handles all timing and execution)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  discover_jobs  │  │  collect_builds │  │  cleanup_data   │             │
│  │  @every 10 min  │  │  @every 5 min   │  │  @daily 2am     │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           ▼                    ▼                    ▼                       │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │              CI Harvester Configuration                      │           │
│  │                                                              │           │
│  │  • Job Priority Rules (which jobs first)                    │           │
│  │  • Rate Limits (requests/min per platform)                  │           │
│  │  • Collection Limits (max builds, log sizes)                │           │
│  │  • Product/Job Overrides                                    │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3. Airflow DAG Schedules

| DAG | Schedule | Configurable Via | Description |
|-----|----------|------------------|-------------|
| `discover_jobs` | `*/10 * * * *` | Airflow Variable | Find new/changed jobs |
| `collect_builds` | `*/5 * * * *` | Airflow Variable | Collect new builds |
| `parse_results` | Triggered | - | Parse test results |
| `cleanup_data` | `0 2 * * *` | Airflow Variable | Data retention |
| `health_check` | `*/5 * * * *` | Airflow Variable | System monitoring |

### Changing Schedules

Schedules are controlled by Airflow Variables:

```python
# In Airflow UI: Admin -> Variables
# Or via CLI:
airflow variables set discovery_schedule "*/10 * * * *"
airflow variables set collection_schedule "*/5 * * * *"

# In DAG definition:
from airflow.models import Variable

with DAG(
    dag_id='collect_builds',
    schedule_interval=Variable.get('collection_schedule', '*/5 * * * *'),
    ...
)
```

## 4. Performance KPIs

### 4.1 Collection Metrics

| KPI | Target | Description |
|-----|--------|-------------|
| **Collection Latency** | < 15 min | Time from build completion to data in DB |
| **Data Freshness** | < 30 min | Max age of any active job's data |
| **Build Collection Rate** | 100+ /min | Throughput when processing backlog |
| **Test Parse Rate** | 1000+ /sec | Test results parsed per second |

### 4.2 System Metrics

| KPI | Target | Description |
|-----|--------|-------------|
| **DAG Success Rate** | > 99% | Percentage of successful DAG runs |
| **Task Duration (p95)** | < 5 min | 95th percentile task time |
| **API Response (p95)** | < 500ms | 95th percentile API latency |
| **Worker Memory** | < 2GB | Per-worker memory limit |

## 5. Configuration System

### 5.1 Configuration Hierarchy

```
┌─────────────────────────────────────────┐
│         Environment Variables           │  ← Highest priority
├─────────────────────────────────────────┤
│          Airflow Variables              │
├─────────────────────────────────────────┤
│      YAML Configuration File            │
├─────────────────────────────────────────┤
│           Default Values                │  ← Lowest priority
└─────────────────────────────────────────┘
```

### 5.2 Configuration File

```yaml
# /etc/ci-harvester/config.yaml
# Or set CI_HARVESTER_CONFIG=/path/to/config.yaml

collection:
  # Maximum jobs to process per DAG run
  max_jobs_per_run: 50
  
  # Maximum builds to collect per job
  max_builds_per_job: 20
  
  # Maximum log size to download (MB)
  max_log_size_mb: 50
  
  # Timeout for collection operations (seconds)
  timeout_seconds: 300

# Rate limits for CI platforms
rate_limits:
  jenkins:
    requests_per_minute: 100
    max_concurrent: 10
  github_actions:
    requests_per_minute: 60
    max_concurrent: 5

# Job priority rules
priorities:
  rules:
    - name: "Production builds"
      match:
        job_pattern: ".*-prod-.*"
        branch: "main"
      priority: CRITICAL
      
    - name: "Release branches"
      match:
        branch_pattern: "release/.*"
      priority: HIGH
  
  # Default for unmatched jobs
  default: NORMAL
  
  # Manual overrides by job name
  overrides:
    "critical-pipeline": CRITICAL
    "nightly-tests": LOW

# Product-specific settings
products:
  MyProduct:
    priority: HIGH
    max_builds_per_job: 50
    
  LegacyProduct:
    priority: LOW
    enabled: true

# Retention settings
retention:
  test_results_days: 365
  build_logs_days: 90
  builds_days: 730
```

### 5.3 Environment Variables

```bash
# Override any setting via environment
CI_HARVESTER_MAX_JOBS_PER_RUN=100
CI_HARVESTER_MAX_BUILDS_PER_JOB=50
CI_HARVESTER_MAX_LOG_SIZE_MB=100
CI_HARVESTER_TIMEOUT_SECONDS=600

# Jenkins rate limits
CI_HARVESTER_JENKINS_REQUESTS_PER_MINUTE=200
CI_HARVESTER_JENKINS_MAX_CONCURRENT=20
```

### 5.4 Airflow Variables

Set via UI (Admin → Variables) or CLI:

```bash
# Collection settings
airflow variables set ci_harvester_max_jobs_per_run 50
airflow variables set ci_harvester_max_builds_per_job 20

# Schedules (cron expressions)
airflow variables set discovery_schedule "*/10 * * * *"
airflow variables set collection_schedule "*/5 * * * *"
airflow variables set cleanup_schedule "0 2 * * *"

# Feature flags
airflow variables set ci_harvester_parse_enabled true
airflow variables set ci_harvester_collect_logs true
```

## 6. Priority System

### 6.1 Priority Levels

| Level | Name | Collection Behavior |
|-------|------|---------------------|
| P0 | CRITICAL | First in queue, no throttling |
| P1 | HIGH | High priority, minimal throttling |
| P2 | NORMAL | Standard processing (default) |
| P3 | LOW | Processed when queue is short |
| P4 | BACKGROUND | Off-peak hours only |

### 6.2 How Priority Works

When a DAG run starts, it queries jobs sorted by priority:

```python
@task
def get_jobs_to_collect() -> List[dict]:
    """Get jobs sorted by priority."""
    config = load_config()
    
    with get_session() as session:
        jobs = session.query(Job).filter(
            Job.is_active == True
        ).order_by(
            Job.last_collected.asc().nullsfirst()
        ).limit(config.max_jobs_per_run).all()
        
        # Apply priority rules
        prioritized = []
        for job in jobs:
            priority = config.get_priority(job.name, job.product.name)
            prioritized.append({
                'id': str(job.id),
                'name': job.name,
                'priority': priority.value,
            })
        
        # Sort by priority (lower = higher priority)
        prioritized.sort(key=lambda j: j['priority'])
        
        return prioritized
```

## 7. Rate Limiting

### 7.1 Purpose

Prevent overwhelming CI platforms with too many API requests.

### 7.2 Implementation

```python
from ratelimit import limits, sleep_and_retry

class RateLimitedCollector:
    """Collector with rate limiting."""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._setup_rate_limiter()
    
    def _setup_rate_limiter(self):
        """Configure rate limiter based on config."""
        calls = self.config.requests_per_minute
        period = 60  # seconds
        
        @sleep_and_retry
        @limits(calls=calls, period=period)
        def rate_limited_request(self, method, *args, **kwargs):
            return method(*args, **kwargs)
        
        self._rate_limited_request = rate_limited_request
    
    def get_builds(self, job_name: str) -> List[Build]:
        """Get builds with rate limiting."""
        return self._rate_limited_request(
            self._client.get_builds,
            job_name
        )
```

### 7.3 Configuration

```yaml
rate_limits:
  jenkins:
    requests_per_minute: 100   # Max 100 requests/min
    max_concurrent: 10         # Max 10 parallel requests
    
  github_actions:
    requests_per_minute: 60    # GitHub has stricter limits
    max_concurrent: 5
```

## 8. Handling High Volume

### 8.1 When Many Jobs Trigger

If many builds complete in a short interval:

1. **DAG runs at scheduled time** (e.g., every 5 min)
2. **Queries jobs** ordered by last_collected (oldest first)
3. **Limits to max_jobs_per_run** (e.g., 50)
4. **Processes in priority order** within that batch
5. **Next DAG run** picks up remaining jobs

### 8.2 Backlog Recovery

```python
# If backlog builds up, temporarily increase throughput
# Set via Airflow Variable or environment

# Increase batch size
airflow variables set ci_harvester_max_jobs_per_run 100

# Increase parallelism
airflow variables set ci_harvester_max_parallel 20

# After backlog clears, restore normal settings
airflow variables set ci_harvester_max_jobs_per_run 50
```

### 8.3 Capacity Estimates

| Scenario | Jobs | Builds/Day | Recommended Settings |
|----------|------|------------|---------------------|
| Small | <50 | <1K | Default (50 jobs, 5min interval) |
| Medium | 50-200 | 1K-10K | 50 jobs, 3min interval |
| Large | 200-500 | 10K-50K | 100 jobs, 2min interval |
| Enterprise | 500+ | 50K+ | 200 jobs, 1min interval |

## 9. Monitoring

### 9.1 Airflow Metrics

Monitor via Airflow UI:
- DAG run duration
- Task success/failure rates
- Task queue depth
- Worker utilization

### 9.2 Custom Metrics

```python
# Exposed at /metrics endpoint (Prometheus format)

# Collection metrics
ci_harvester_builds_collected_total{product, job, status}
ci_harvester_collection_duration_seconds{product, job}
ci_harvester_tests_parsed_total{product, job}

# Data freshness
ci_harvester_job_last_collected_timestamp{product, job}
ci_harvester_stale_jobs_count{threshold}

# Rate limiting
ci_harvester_rate_limit_delays_total{platform}
ci_harvester_rate_limit_delay_seconds{platform}
```

### 9.3 Alerts

```yaml
# Configure in your monitoring system (Prometheus/Grafana/etc.)

alerts:
  - name: StaleData
    expr: time() - ci_harvester_job_last_collected_timestamp > 1800
    severity: warning
    message: "Job {{ job }} data is stale (>30 min)"
    
  - name: CollectionBacklog
    expr: ci_harvester_stale_jobs_count{threshold="30m"} > 10
    severity: warning
    message: "{{ value }} jobs have stale data"
    
  - name: HighErrorRate
    expr: rate(ci_harvester_collection_errors_total[5m]) > 0.1
    severity: critical
    message: "Collection error rate above 10%"
```

## 10. Example Configurations

### 10.1 Default (Balanced)

```yaml
collection:
  max_jobs_per_run: 50
  max_builds_per_job: 20
  max_log_size_mb: 50

rate_limits:
  jenkins:
    requests_per_minute: 100
    max_concurrent: 10

# Airflow schedule: every 5 minutes
```

### 10.2 Low Latency (Real-time Monitoring)

```yaml
collection:
  max_jobs_per_run: 100
  max_builds_per_job: 10
  max_log_size_mb: 20

rate_limits:
  jenkins:
    requests_per_minute: 200
    max_concurrent: 20

# Airflow schedule: every 1-2 minutes
```

### 10.3 Resource Efficient (Limited Resources)

```yaml
collection:
  max_jobs_per_run: 20
  max_builds_per_job: 50
  max_log_size_mb: 100

rate_limits:
  jenkins:
    requests_per_minute: 50
    max_concurrent: 5

# Airflow schedule: every 10-15 minutes
```

## 11. Changing Settings at Runtime

### 11.1 Via Airflow UI

1. Go to Admin → Variables
2. Update the relevant variable
3. Next DAG run will use new value

### 11.2 Via CLI

```bash
# Update collection batch size
airflow variables set ci_harvester_max_jobs_per_run 100

# Update schedule (requires DAG reload)
airflow variables set collection_schedule "*/2 * * * *"
airflow dags reserialize
```

### 11.3 Via API (Future)

```bash
# Update configuration
curl -X PATCH http://localhost:8000/api/v1/config \
  -H "Content-Type: application/json" \
  -d '{"max_jobs_per_run": 100}'

# Set job priority
curl -X PUT http://localhost:8000/api/v1/jobs/{job_id}/priority \
  -H "Content-Type: application/json" \
  -d '{"priority": "HIGH"}'
```
