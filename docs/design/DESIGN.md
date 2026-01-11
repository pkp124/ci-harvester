# CI Harvester - Design Document

## 1. Executive Summary

CI Harvester is a data pipeline system that collects, parses, and stores CI/CD build logs and test results from various continuous integration platforms. The initial implementation focuses on Jenkins as the CI source and CTest as the test framework, with PostgreSQL as the persistent storage layer and Apache Airflow as the workflow orchestrator.

## 2. Goals and Non-Goals

### 2.1 Goals

1. **Automated Collection**: Periodically scrape build logs and test results from Jenkins jobs
2. **Structured Storage**: Store raw logs and parsed test results in PostgreSQL with queryable schema
3. **Extensibility**: Design for easy addition of new CI platforms (GitHub Actions, GitLab CI, etc.)
4. **Test Framework Agnostic**: Support multiple test result formats (CTest, JUnit, TAP, etc.)
5. **Reliable Orchestration**: Use Airflow for scheduling, retries, and monitoring
6. **Historical Analysis**: Enable trend analysis and failure pattern detection over time
7. **API Access**: Provide REST API for querying harvested data

### 2.2 Non-Goals

1. Real-time streaming of logs (batch processing is sufficient)
2. Build triggering or CI control (read-only harvesting)
3. Replacing CI platform UIs (complement, not replace)
4. Complex analytics or ML (focus on data collection and storage)

## 3. Architecture Overview

### 3.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CI Harvester System                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐     ┌──────────────────────────────────────────────────┐  │
│  │   Jenkins   │────▶│                  Apache Airflow                   │  │
│  │   Server    │     │  ┌────────────┐  ┌────────────┐  ┌────────────┐  │  │
│  └─────────────┘     │  │  Discover  │─▶│  Collect   │─▶│   Parse    │  │  │
│                      │  │    DAG     │  │    DAG     │  │    DAG     │  │  │
│  ┌─────────────┐     │  └────────────┘  └────────────┘  └────────────┘  │  │
│  │ GitHub CI   │────▶│         │              │              │          │  │
│  │  (future)   │     │         ▼              ▼              ▼          │  │
│  └─────────────┘     └─────────┼──────────────┼──────────────┼──────────┘  │
│                                │              │              │             │
│                                ▼              ▼              ▼             │
│                      ┌─────────────────────────────────────────────────┐   │
│                      │                 CI Harvester Core               │   │
│                      │  ┌────────────┐  ┌────────────┐  ┌──────────┐  │   │
│                      │  │ Collectors │  │  Parsers   │  │ DB Layer │  │   │
│                      │  │  (Jenkins) │  │  (CTest)   │  │  (SQLAlch)│  │   │
│                      │  └────────────┘  └────────────┘  └──────────┘  │   │
│                      └─────────────────────────┬───────────────────────┘   │
│                                                │                           │
│                                                ▼                           │
│                      ┌─────────────────────────────────────────────────┐   │
│                      │                  PostgreSQL                      │   │
│                      └─────────────────────────────────────────────────┘   │
│                                                │                           │
│                                                ▼                           │
│                      ┌─────────────────────────────────────────────────┐   │
│                      │               REST API (FastAPI)                 │   │
│                      └─────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Model Hierarchy

```
┌─────────────────┐
│    Products     │  Top-level grouping (e.g., software products)
└────────┬────────┘
         │ 1:N
         ▼
┌─────────────────┐
│      Jobs       │  CI jobs belonging to a product
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    │ 1:N     │ 1:N
    ▼         ▼
┌────────┐ ┌────────┐
│ Builds │ │ Tests  │  Test definitions (persistent across builds)
└───┬────┘ └───┬────┘
    │          │
    │ 1:N      │
    ▼          │
┌────────────────────┐
│  Test Executions   │◄─────────────────────┘ N:1
└─────────┬──────────┘  Execution of a test in a specific build
          │
          │ 1:N
          ▼
┌─────────────────────┐
│  CTest Measurements │  Measurements captured during execution
└─────────────────────┘
```

**Key Concepts:**

- **Products**: Group related CI jobs (e.g., "MyProduct", "Platform Libraries")
- **Jobs**: CI pipelines belonging to a product, with CI source info (Jenkins, etc.)
- **Tests**: Test definitions discovered from jobs, persistent across builds
- **Builds**: Individual runs of a job
- **Test Executions**: Execution of a test within a specific build
- **CTest Measurements**: Metrics from CTest (execution time, memory, etc.)

## 4. Component Design

### 4.1 Collectors

Collectors are responsible for interfacing with CI platforms to discover jobs and fetch build data.

```python
# Abstract base class for collectors
class BaseCollector(ABC):
    @abstractmethod
    def discover_jobs(self) -> List[JobInfo]:
        """Discover available jobs/pipelines"""
        pass
    
    @abstractmethod
    def get_builds(self, job_id: str, since: datetime) -> List[BuildInfo]:
        """Get builds for a job since a given time"""
        pass
    
    @abstractmethod
    def get_build_log(self, job_id: str, build_id: str) -> str:
        """Fetch the console log for a build"""
        pass
    
    @abstractmethod
    def get_artifacts(self, job_id: str, build_id: str) -> List[Artifact]:
        """List and fetch build artifacts"""
        pass
```

#### Jenkins Collector
- Uses Jenkins REST API with python-jenkins library
- Supports both username/password and API token authentication
- Handles pagination for large job/build lists
- Downloads console logs and XML test result artifacts

### 4.2 Parsers

Parsers extract structured test results from various formats.

```python
# Abstract base class for parsers
class BaseParser(ABC):
    @abstractmethod
    def can_parse(self, content: bytes, filename: str) -> bool:
        """Check if this parser can handle the content"""
        pass
    
    @abstractmethod
    def parse(self, content: bytes) -> TestResults:
        """Parse content into structured test results"""
        pass
```

#### CTest Parser
- Parses CTest XML output (Testing/*/Test.xml)
- Extracts test name, status, duration, output
- Handles CTest's multi-part result structure
- Supports both TAGged and direct XML formats

### 4.3 Database Layer

SQLAlchemy-based ORM with PostgreSQL-specific optimizations.

Key design decisions:
- Use UUIDs for primary keys (distributed-friendly)
- Partition large tables by date (logs, test_results)
- Store raw logs with compression
- Use JSONB for flexible metadata storage

### 4.4 Workflow Orchestrator

#### Why Airflow over n8n?

| Criteria | Airflow | n8n |
|----------|---------|-----|
| **Python Native** | ✅ Yes | ❌ Node.js |
| **Data Pipeline Focus** | ✅ Designed for ETL | ⚠️ General automation |
| **Scheduling** | ✅ Cron + sensors | ✅ Cron-based |
| **Retry/Backfill** | ✅ Built-in | ⚠️ Limited |
| **Monitoring** | ✅ Rich UI & metrics | ✅ Good UI |
| **Code-as-Config** | ✅ DAGs in Python | ❌ Visual/JSON |
| **Community** | ✅ Large, mature | ⚠️ Growing |
| **CI/CD Integration** | ✅ Many operators | ⚠️ Fewer |

**Recommendation**: Apache Airflow is better suited for this use case because:
1. Native Python integration with our collectors/parsers
2. Superior handling of data pipelines and backfilling
3. Better retry and failure handling semantics
4. Industry standard for ETL workloads

### 4.5 REST API

FastAPI-based API for querying harvested data.

Key endpoints:
- `GET /jobs` - List discovered CI jobs
- `GET /jobs/{id}/builds` - List builds for a job
- `GET /builds/{id}` - Get build details
- `GET /builds/{id}/logs` - Get build logs
- `GET /builds/{id}/tests` - Get test results
- `GET /tests/failures` - Query test failures across builds

## 5. Data Flow

### 5.1 Discovery Flow

```
┌──────────┐     ┌──────────────┐     ┌────────────┐
│ Airflow  │────▶│   Jenkins    │────▶│ PostgreSQL │
│ Schedule │     │  Collector   │     │   (jobs)   │
└──────────┘     └──────────────┘     └────────────┘
     │                                       │
     │           Runs every hour             │
     │           Discovers new jobs          │
     └───────────────────────────────────────┘
```

### 5.2 Collection Flow

```
┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
│ Airflow  │────▶│   Jenkins    │────▶│    CTest     │────▶│ PostgreSQL │
│ Schedule │     │  Collector   │     │    Parser    │     │  (builds,  │
└──────────┘     └──────────────┘     └──────────────┘     │   tests)   │
     │                  │                    │              └────────────┘
     │                  │                    │                    │
     │  For each job:   │  Fetch logs &      │  Parse test        │
     │  - Get new builds│  artifacts         │  results           │
     └──────────────────┴────────────────────┴────────────────────┘
```

## 6. Deployment Architecture

### 6.1 Development

```
┌─────────────────────────────────────────────────┐
│              Docker Compose Stack               │
├─────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐              │
│  │  Airflow    │  │  PostgreSQL │              │
│  │  Standalone │  │    :5432    │              │
│  │    :8080    │  └─────────────┘              │
│  └─────────────┘                               │
│  ┌─────────────┐  ┌─────────────┐              │
│  │    API      │  │   Redis     │              │
│  │    :8000    │  │   :6379     │              │
│  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────┘
```

### 6.2 Production

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                           │
├─────────────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    Airflow Helm Chart                         │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │ │
│  │  │  Scheduler  │  │   Webserver │  │   Workers   │           │ │
│  │  │   (1 pod)   │  │   (2 pods)  │  │  (3+ pods)  │           │ │
│  │  └─────────────┘  └─────────────┘  └─────────────┘           │ │
│  └───────────────────────────────────────────────────────────────┘ │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                │
│  │    API      │  │ PostgreSQL  │  │    Redis    │                │
│  │  (3 pods)   │  │   (RDS/HA)  │  │  (cluster)  │                │
│  └─────────────┘  └─────────────┘  └─────────────┘                │
└─────────────────────────────────────────────────────────────────────┘
```

## 7. Security Considerations

### 7.1 Authentication & Authorization
- Jenkins API credentials stored in Airflow connections (encrypted)
- PostgreSQL with role-based access control
- API authentication via API keys or OAuth2

### 7.2 Data Protection
- Logs may contain sensitive data - consider scrubbing/masking
- Network isolation between components
- TLS for all external communications

### 7.3 Secrets Management
- Use Airflow's built-in secrets backend
- Support for external secrets (Vault, AWS Secrets Manager)

## 8. Extensibility

### 8.1 Adding New CI Platforms

1. Create new collector class implementing `BaseCollector`
2. Register collector in collector factory
3. Add Airflow connection type
4. Update discovery DAG to include new platform

### 8.2 Adding New Test Frameworks

1. Create new parser class implementing `BaseParser`
2. Register parser in parser factory
3. Parser auto-detection based on file content/name

### 8.3 Plugin System

Future enhancement: plugin-based architecture for collectors and parsers.

## 9. Monitoring & Observability

### 9.1 Metrics
- Collection success/failure rates
- Parse success/failure rates
- Data freshness (time since last collection)
- Database size growth

### 9.2 Logging
- Structured logging (JSON format)
- Log aggregation (ELK, CloudWatch, etc.)
- Request tracing with correlation IDs

### 9.3 Alerting
- Airflow DAG failures
- Collection errors
- Database connection issues
- API availability

## 10. Future Enhancements

1. **Additional CI Platforms**: GitHub Actions, GitLab CI, CircleCI, Azure DevOps
2. **Additional Test Frameworks**: JUnit, pytest, TAP, GoogleTest
3. **Analytics Dashboard**: Grafana dashboards for test trends
4. **ML Integration**: Failure prediction, flaky test detection
5. **Webhooks**: Real-time triggers from CI systems
6. **Data Retention**: Configurable retention policies with archival

## 11. Decision Log

| Decision | Rationale | Date |
|----------|-----------|------|
| PostgreSQL over MongoDB | Structured test data, complex queries, ACID compliance | 2024-01 |
| Airflow over n8n | Python native, data pipeline focus, mature ecosystem | 2024-01 |
| FastAPI for REST | Modern, fast, auto-documentation, async support | 2024-01 |
| SQLAlchemy ORM | Python standard, good PostgreSQL support | 2024-01 |
| Jenkins first | Most common enterprise CI, well-documented API | 2024-01 |
| CTest first | User requirement, XML format is parseable | 2024-01 |
