# CI Harvester - Scheduling Policy

## 1. Overview

This document defines the scheduling policy for CI Harvester, including collection intervals, prioritization, rate limiting, and performance KPIs. The policy is designed to be user-configurable while maintaining system stability.

## 2. Performance KPIs

### 2.1 Collection Metrics

| KPI | Target | Description |
|-----|--------|-------------|
| **Collection Latency** | < 15 min | Time from build completion to data availability |
| **Discovery Interval** | 10 min | How often new jobs are discovered |
| **Build Collection Rate** | 100+ builds/min | Throughput of build collection |
| **Test Parse Rate** | 1000+ tests/sec | Throughput of test result parsing |
| **Data Freshness** | < 30 min | Max age of any active job's data |

### 2.2 System Metrics

| KPI | Target | Description |
|-----|--------|-------------|
| **API Response Time (p95)** | < 500ms | 95th percentile API latency |
| **Collection Success Rate** | > 99% | Percentage of successful collections |
| **Parser Success Rate** | > 99.5% | Percentage of successful parses |
| **Database Write Latency (p95)** | < 100ms | 95th percentile DB write time |
| **Memory Usage** | < 2GB | Per-worker memory limit |

### 2.3 Capacity Planning

| Metric | Estimate | Notes |
|--------|----------|-------|
| **Builds per day** | ~10,000 | 100 jobs × 100 builds/day |
| **Log data per day** | ~10 GB | 10K builds × 1 MB avg log |
| **Test results per day** | ~500K | 10K builds × 50 tests avg |
| **Measurements per day** | ~2.5M | 500K tests × 5 measurements |

## 3. Scheduling Architecture

### 3.1 Collection Tiers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Collection Scheduler                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │   DISCOVERY     │  │   COLLECTION    │  │    PARSING      │             │
│  │   (10 min)      │  │   (5 min)       │  │   (triggered)   │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           ▼                    ▼                    ▼                       │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │                    Priority Queue                            │           │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │           │
│  │  │ CRITICAL │ │   HIGH   │ │  NORMAL  │ │   LOW    │       │           │
│  │  │  (P0)    │ │   (P1)   │ │   (P2)   │ │   (P3)   │       │           │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │                    Worker Pool                               │           │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐    │           │
│  │  │Worker 1│ │Worker 2│ │Worker 3│ │Worker 4│ │Worker N│    │           │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘    │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Schedule Overview

| Task | Default Interval | Configurable Range | Description |
|------|------------------|-------------------|-------------|
| Job Discovery | 10 min | 5-60 min | Find new/changed jobs |
| Build Collection | 5 min | 1-30 min | Collect new builds |
| Test Parsing | Triggered | - | Parse on artifact detection |
| Cleanup | Daily 2 AM | Configurable | Data retention cleanup |
| Health Check | 5 min | 1-15 min | System monitoring |

## 4. Priority System

### 4.1 Priority Levels

```python
class JobPriority(Enum):
    CRITICAL = 0   # P0: Collect immediately, max resources
    HIGH = 1       # P1: Collect within 5 minutes
    NORMAL = 2     # P2: Collect within 15 minutes (default)
    LOW = 3        # P3: Collect when resources available
    BACKGROUND = 4 # P4: Collect during off-peak hours
```

### 4.2 Priority Assignment

Jobs can be assigned priority based on:

```yaml
# scheduling_config.yaml
priority_rules:
  # Rule-based priority assignment
  rules:
    - name: "Production builds"
      match:
        job_name_pattern: ".*-prod-.*"
        branch: "main"
      priority: CRITICAL
      
    - name: "Release branches"
      match:
        branch_pattern: "release/.*"
      priority: HIGH
      
    - name: "Feature branches"
      match:
        branch_pattern: "feature/.*"
      priority: NORMAL
      
    - name: "Experimental"
      match:
        job_name_pattern: ".*-experimental-.*"
      priority: LOW

  # Default priority for unmatched jobs
  default_priority: NORMAL
  
  # Manual overrides (job_id -> priority)
  overrides:
    "critical-pipeline": CRITICAL
    "nightly-tests": BACKGROUND
```

### 4.3 Dynamic Priority Adjustment

```python
# Priority increases when:
# - Build has been waiting too long
# - Previous collection failed (retry)
# - Job has high failure rate (needs monitoring)

def calculate_effective_priority(job: Job, base_priority: int) -> int:
    priority = base_priority
    
    # Aging: increase priority if waiting too long
    wait_time = now() - job.last_collected
    if wait_time > timedelta(minutes=30):
        priority = max(0, priority - 1)  # Boost priority
    
    # Failed builds need attention
    if job.recent_failure_rate > 0.5:
        priority = max(0, priority - 1)
    
    # Retry boost
    if job.pending_retry:
        priority = max(0, priority - 1)
    
    return priority
```

## 5. Rate Limiting

### 5.1 CI Platform Rate Limits

```yaml
# rate_limits.yaml
rate_limits:
  jenkins:
    # Requests per minute to Jenkins API
    requests_per_minute: 100
    
    # Concurrent connections
    max_concurrent: 10
    
    # Delay between requests (ms)
    min_request_interval_ms: 100
    
    # Backoff on rate limit response
    backoff:
      initial_delay_ms: 1000
      max_delay_ms: 60000
      multiplier: 2
  
  github_actions:
    requests_per_minute: 60
    max_concurrent: 5
    min_request_interval_ms: 200
```

### 5.2 Internal Rate Limiting

```yaml
# Limit collection throughput to prevent overload
collection_limits:
  # Maximum builds to collect per interval
  max_builds_per_interval: 500
  
  # Maximum concurrent job collections
  max_concurrent_jobs: 20
  
  # Maximum log size to download (MB)
  max_log_size_mb: 50
  
  # Maximum artifacts per build
  max_artifacts_per_build: 100
  
  # Maximum total artifact size per build (MB)
  max_artifact_size_mb: 100
```

## 6. Backpressure Handling

### 6.1 Queue Management

```
┌─────────────────────────────────────────────────────────────────┐
│                      Backpressure Control                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Queue Depth Thresholds:                                        │
│                                                                  │
│  0%─────25%─────50%─────75%─────100%                           │
│  │       │       │       │        │                             │
│  │ NORMAL│ SLOW  │ PAUSE │ DROP   │                             │
│  │       │ DOWN  │ LOW   │ LOW    │                             │
│  │       │       │PRIORITY│PRIORITY│                            │
│                                                                  │
│  Actions:                                                        │
│  - 0-25%:   Normal operation                                    │
│  - 25-50%:  Reduce collection frequency                         │
│  - 50-75%:  Pause LOW priority, alert                          │
│  - 75-100%: Drop BACKGROUND, pause LOW, alert critical         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Configuration

```yaml
backpressure:
  # Queue depth thresholds
  thresholds:
    warning: 0.25      # 25% - start slowing down
    critical: 0.50     # 50% - pause low priority
    emergency: 0.75    # 75% - drop background jobs
  
  # Actions at each level
  actions:
    warning:
      - reduce_collection_frequency: 0.5  # 50% slower
      - alert: warning
    
    critical:
      - pause_priority: [LOW, BACKGROUND]
      - alert: critical
    
    emergency:
      - drop_priority: [BACKGROUND]
      - pause_priority: [LOW, NORMAL]
      - alert: emergency
  
  # Recovery settings
  recovery:
    # Resume paused jobs when queue drops below
    resume_threshold: 0.20
    # Gradual recovery rate
    recovery_rate: 0.1  # 10% more jobs per interval
```

## 7. User-Configurable Settings

### 7.1 Global Settings

```yaml
# /etc/ci-harvester/scheduling.yaml
# Or via environment variables / Airflow Variables

scheduling:
  # Discovery interval (how often to look for new jobs)
  discovery_interval_minutes: 10
  
  # Collection interval (how often to collect builds)
  collection_interval_minutes: 5
  
  # Maximum jobs to process per collection cycle
  max_jobs_per_cycle: 50
  
  # Maximum builds to collect per job
  max_builds_per_job: 20
  
  # Parallelism
  max_parallel_collections: 10
  max_parallel_parsers: 20
  
  # Timeouts
  collection_timeout_seconds: 300
  parse_timeout_seconds: 120
  
  # Retry policy
  retry:
    max_attempts: 3
    initial_delay_seconds: 60
    max_delay_seconds: 3600
    exponential_base: 2
```

### 7.2 Per-Product Settings

```yaml
# Product-specific overrides
products:
  MyProduct:
    # Override global settings for this product
    collection_interval_minutes: 2  # More frequent
    priority: HIGH
    max_builds_per_job: 50
    
  LegacyProduct:
    collection_interval_minutes: 30  # Less frequent
    priority: LOW
    enabled: true
    
  ExperimentalProduct:
    enabled: false  # Disable collection
```

### 7.3 Per-Job Settings

```yaml
# Job-specific overrides
jobs:
  "production-build":
    priority: CRITICAL
    collection_interval_minutes: 1
    max_builds: 100
    alerts:
      on_failure: true
      on_flaky_test: true
      
  "nightly-integration":
    priority: BACKGROUND
    collection_window:
      start: "02:00"
      end: "06:00"
      timezone: "UTC"
```

### 7.4 API for Runtime Configuration

```python
# REST API endpoints for runtime configuration

# Get current scheduling config
GET /api/v1/config/scheduling

# Update global settings
PATCH /api/v1/config/scheduling
{
  "discovery_interval_minutes": 5,
  "max_parallel_collections": 15
}

# Set job priority
PUT /api/v1/jobs/{job_id}/priority
{
  "priority": "HIGH",
  "reason": "Release week"
}

# Pause/resume job collection
POST /api/v1/jobs/{job_id}/pause
POST /api/v1/jobs/{job_id}/resume

# Trigger immediate collection
POST /api/v1/jobs/{job_id}/collect
{
  "priority": "CRITICAL",
  "include_builds": [142, 143, 144]
}
```

## 8. Scheduling DAGs

### 8.1 Master Scheduler DAG

```python
# dags/scheduler_master.py

@dag(
    schedule_interval=None,  # Triggered by sensor
    catchup=False,
    max_active_runs=1,
)
def scheduler_master():
    """
    Master scheduler that coordinates all collection activities.
    """
    
    @task
    def load_scheduling_config() -> dict:
        """Load current scheduling configuration."""
        return SchedulingConfig.load()
    
    @task
    def get_pending_jobs(config: dict) -> list:
        """Get jobs due for collection based on priority and schedule."""
        return JobScheduler.get_pending_jobs(
            max_jobs=config['max_jobs_per_cycle'],
            priorities=[P0, P1, P2, P3]
        )
    
    @task
    def check_backpressure() -> dict:
        """Check system load and adjust collection rate."""
        return BackpressureController.get_status()
    
    @task
    def apply_backpressure(jobs: list, status: dict) -> list:
        """Filter jobs based on backpressure status."""
        if status['level'] == 'emergency':
            return [j for j in jobs if j['priority'] <= P1]
        elif status['level'] == 'critical':
            return [j for j in jobs if j['priority'] <= P2]
        return jobs
    
    @task
    def schedule_collections(jobs: list):
        """Schedule collection tasks for jobs."""
        for job in jobs:
            trigger_dag_run(
                dag_id='collect_job',
                conf={'job_id': job['id'], 'priority': job['priority']}
            )
    
    # Flow
    config = load_scheduling_config()
    jobs = get_pending_jobs(config)
    bp_status = check_backpressure()
    filtered_jobs = apply_backpressure(jobs, bp_status)
    schedule_collections(filtered_jobs)
```

### 8.2 Collection DAG

```python
# dags/collect_job.py

@dag(
    schedule_interval=None,
    catchup=False,
    max_active_runs=50,  # Allow parallel job collections
    default_args={
        'retries': 3,
        'retry_delay': timedelta(minutes=1),
        'retry_exponential_backoff': True,
    }
)
def collect_job():
    """Collect builds for a single job."""
    
    @task
    def collect_builds(job_id: str, priority: int) -> list:
        """Collect new builds from CI platform."""
        config = SchedulingConfig.load()
        collector = get_collector_for_job(job_id)
        
        # Apply rate limiting
        with RateLimiter(collector.platform):
            builds = collector.get_new_builds(
                max_builds=config['max_builds_per_job'],
                timeout=config['collection_timeout_seconds']
            )
        
        return builds
    
    @task
    def save_builds(builds: list) -> list:
        """Save builds to database."""
        saved = []
        with get_session() as session:
            for build in builds:
                saved.append(BuildRepository.save(session, build))
            session.commit()
        return saved
    
    @task
    def collect_logs(builds: list) -> list:
        """Collect logs for builds."""
        config = SchedulingConfig.load()
        results = []
        
        for build in builds:
            try:
                log = collector.get_log(
                    build['id'],
                    max_size=config['max_log_size_mb'] * 1024 * 1024
                )
                results.append({'build_id': build['id'], 'log': log})
            except Exception as e:
                logger.warning("log_collection_failed", build=build['id'], error=str(e))
        
        return results
    
    @task
    def trigger_parsing(builds: list):
        """Trigger test result parsing for builds with artifacts."""
        for build in builds:
            if build.get('has_test_artifacts'):
                trigger_dag_run(
                    dag_id='parse_test_results',
                    conf={'build_id': build['id']}
                )
    
    # Flow
    job_id = "{{ dag_run.conf['job_id'] }}"
    priority = "{{ dag_run.conf['priority'] }}"
    
    builds = collect_builds(job_id, priority)
    saved = save_builds(builds)
    logs = collect_logs(saved)
    trigger_parsing(saved)
```

## 9. Monitoring & Alerting

### 9.1 Metrics to Monitor

```python
# Prometheus metrics
from prometheus_client import Counter, Histogram, Gauge

# Collection metrics
builds_collected = Counter(
    'ci_harvester_builds_collected_total',
    'Total builds collected',
    ['product', 'job', 'status']
)

collection_duration = Histogram(
    'ci_harvester_collection_duration_seconds',
    'Time to collect a job',
    ['product', 'job']
)

collection_queue_depth = Gauge(
    'ci_harvester_collection_queue_depth',
    'Current collection queue depth',
    ['priority']
)

# Data freshness
data_age_seconds = Gauge(
    'ci_harvester_data_age_seconds',
    'Age of most recent data for job',
    ['product', 'job']
)

# Error rates
collection_errors = Counter(
    'ci_harvester_collection_errors_total',
    'Collection errors',
    ['product', 'job', 'error_type']
)
```

### 9.2 Alerts

```yaml
# alerting_rules.yaml
alerts:
  - name: HighCollectionLatency
    condition: avg(collection_duration) > 300  # 5 minutes
    severity: warning
    message: "Collection taking longer than expected"
    
  - name: StaleData
    condition: max(data_age_seconds) > 1800  # 30 minutes
    severity: critical
    message: "Data for {{ job }} is {{ age }} minutes old"
    
  - name: HighErrorRate
    condition: rate(collection_errors[5m]) > 0.1
    severity: critical
    message: "Collection error rate above 10%"
    
  - name: QueueBacklog
    condition: collection_queue_depth > 1000
    severity: warning
    message: "Collection queue has {{ depth }} pending jobs"
    
  - name: BackpressureActive
    condition: backpressure_level != "normal"
    severity: warning
    message: "Backpressure active at {{ level }} level"
```

## 10. Capacity Planning

### 10.1 Resource Estimation

```python
# Estimate resources needed based on workload

def estimate_resources(
    jobs_count: int,
    builds_per_job_per_day: int,
    avg_log_size_mb: float,
    avg_tests_per_build: int,
    collection_interval_minutes: int
) -> dict:
    """Estimate required resources."""
    
    # Builds per interval
    intervals_per_day = 24 * 60 / collection_interval_minutes
    builds_per_day = jobs_count * builds_per_job_per_day
    builds_per_interval = builds_per_day / intervals_per_day
    
    # Data volume
    logs_per_day_gb = builds_per_day * avg_log_size_mb / 1024
    tests_per_day = builds_per_day * avg_tests_per_build
    
    # Workers needed (assuming 10 builds/min per worker)
    collection_workers = ceil(builds_per_interval / 10)
    
    # Memory (assuming 100MB per worker)
    memory_gb = collection_workers * 0.1 + 2  # +2GB base
    
    # Database storage per month
    storage_gb_per_month = (
        logs_per_day_gb * 30 +  # Logs
        tests_per_day * 30 * 0.001  # Test results (~1KB each)
    )
    
    return {
        'builds_per_day': builds_per_day,
        'builds_per_interval': builds_per_interval,
        'collection_workers': collection_workers,
        'memory_gb': memory_gb,
        'storage_gb_per_month': storage_gb_per_month,
        'logs_per_day_gb': logs_per_day_gb,
        'tests_per_day': tests_per_day
    }

# Example calculation
estimate_resources(
    jobs_count=100,
    builds_per_job_per_day=50,
    avg_log_size_mb=2,
    avg_tests_per_build=100,
    collection_interval_minutes=5
)
# Returns:
# {
#   'builds_per_day': 5000,
#   'builds_per_interval': 17,
#   'collection_workers': 2,
#   'memory_gb': 2.2,
#   'storage_gb_per_month': 300,
#   'logs_per_day_gb': 10,
#   'tests_per_day': 500000
# }
```

### 10.2 Scaling Recommendations

| Workload | Jobs | Builds/Day | Workers | Memory | Storage/Month |
|----------|------|------------|---------|--------|---------------|
| Small | 10-50 | 500-2K | 1-2 | 2-4 GB | 10-50 GB |
| Medium | 50-200 | 2K-10K | 2-5 | 4-8 GB | 50-200 GB |
| Large | 200-1000 | 10K-50K | 5-15 | 8-16 GB | 200-1000 GB |
| Enterprise | 1000+ | 50K+ | 15+ | 16+ GB | 1+ TB |

## 11. Configuration Examples

### 11.1 Low-Latency Configuration

For real-time monitoring needs:

```yaml
scheduling:
  discovery_interval_minutes: 5
  collection_interval_minutes: 1
  max_parallel_collections: 30
  max_builds_per_job: 10
  
priority_rules:
  default_priority: HIGH
  
rate_limits:
  jenkins:
    requests_per_minute: 200
    max_concurrent: 20
```

### 11.2 Resource-Efficient Configuration

For limited resources:

```yaml
scheduling:
  discovery_interval_minutes: 30
  collection_interval_minutes: 15
  max_parallel_collections: 5
  max_builds_per_job: 50
  
priority_rules:
  default_priority: NORMAL
  
backpressure:
  thresholds:
    warning: 0.15
    critical: 0.30
    emergency: 0.50
```

### 11.3 High-Volume Configuration

For large-scale deployments:

```yaml
scheduling:
  discovery_interval_minutes: 10
  collection_interval_minutes: 5
  max_parallel_collections: 50
  max_builds_per_job: 100
  
rate_limits:
  jenkins:
    requests_per_minute: 500
    max_concurrent: 50
    
backpressure:
  thresholds:
    warning: 0.40
    critical: 0.60
    emergency: 0.80
```
