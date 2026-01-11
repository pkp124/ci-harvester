# CI Harvester - Airflow Workflows

## 1. Overview

This document describes the Apache Airflow DAGs (Directed Acyclic Graphs) that orchestrate the CI Harvester data collection workflows. Airflow provides scheduling, monitoring, retry logic, and dependency management for the harvesting pipelines.

## 2. Why Airflow

### 2.1 Key Benefits

| Feature | Benefit for CI Harvester |
|---------|-------------------------|
| **Python Native** | Direct integration with collectors/parsers |
| **Scheduling** | Cron-based collection schedules |
| **Backfill** | Collect historical data |
| **Retry Logic** | Automatic retry on failures |
| **Parallelism** | Collect from multiple jobs concurrently |
| **Monitoring** | Web UI for pipeline visibility |
| **Connections** | Secure credential storage |
| **XComs** | Pass data between tasks |

### 2.2 Comparison with n8n

| Aspect | Airflow | n8n |
|--------|---------|-----|
| Language | Python | TypeScript/Node.js |
| Configuration | Code (DAGs) | Visual/JSON |
| Data Pipelines | Excellent | Good |
| Complex Logic | Native Python | Limited |
| Community | Very large | Growing |
| Hosting | Self-hosted | Self-hosted or cloud |

**Decision**: Airflow is chosen for its Python-native approach and superior data pipeline handling.

## 3. DAG Architecture

### 3.1 DAG Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Airflow DAGs                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────┐         ┌─────────────────────┐                    │
│  │   discover_jobs     │         │   collect_builds    │                    │
│  │   (hourly)          │─────────│   (every 15 min)    │                    │
│  └─────────────────────┘         └─────────────────────┘                    │
│           │                               │                                  │
│           │                               │                                  │
│           ▼                               ▼                                  │
│  ┌─────────────────────┐         ┌─────────────────────┐                    │
│  │   jobs table        │         │   builds table      │                    │
│  │   (PostgreSQL)      │         │   (PostgreSQL)      │                    │
│  └─────────────────────┘         └─────────────────────┘                    │
│                                           │                                  │
│                                           ▼                                  │
│                                  ┌─────────────────────┐                    │
│                                  │   parse_tests       │                    │
│                                  │   (triggered)       │                    │
│                                  └─────────────────────┘                    │
│                                           │                                  │
│                                           ▼                                  │
│                                  ┌─────────────────────┐                    │
│                                  │   test_results      │                    │
│                                  │   (PostgreSQL)      │                    │
│                                  └─────────────────────┘                    │
│                                                                              │
│  ┌─────────────────────┐         ┌─────────────────────┐                    │
│  │   cleanup_old_data  │         │   backfill_builds   │                    │
│  │   (daily)           │         │   (manual)          │                    │
│  └─────────────────────┘         └─────────────────────┘                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 DAG List

| DAG ID | Schedule | Purpose |
|--------|----------|---------|
| `discover_jobs` | `0 * * * *` (hourly) | Discover new/changed jobs |
| `collect_builds` | `*/15 * * * *` (15 min) | Collect new builds and logs |
| `parse_test_results` | Triggered | Parse test artifacts |
| `cleanup_old_data` | `0 2 * * *` (daily 2am) | Data retention cleanup |
| `backfill_builds` | Manual | Historical data collection |
| `health_check` | `*/5 * * * *` (5 min) | System health monitoring |

## 4. DAG Implementations

### 4.1 Discover Jobs DAG

```python
# dags/discover_jobs.py
"""
DAG to discover CI jobs from configured sources.
Runs hourly to find new or changed jobs.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable
from airflow.hooks.base import BaseHook

default_args = {
    'owner': 'ci-harvester',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(minutes=30),
}

with DAG(
    dag_id='discover_jobs',
    default_args=default_args,
    description='Discover CI jobs from all configured sources',
    schedule_interval='0 * * * *',  # Every hour
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ci-harvester', 'discovery'],
) as dag:
    
    @task
    def get_active_sources() -> list:
        """Get list of active CI sources from database."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import CISource
        
        with get_session() as session:
            sources = session.query(CISource).filter(
                CISource.is_active == True
            ).all()
            return [
                {
                    'id': str(s.id),
                    'name': s.name,
                    'type': s.type,
                    'base_url': s.base_url,
                    'config': s.config
                }
                for s in sources
            ]
    
    @task
    def discover_jobs_for_source(source: dict) -> dict:
        """Discover jobs for a single source."""
        from ci_harvester.collectors import get_collector
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Get collector for source type
        collector = get_collector(
            source_type=source['type'],
            connection_id=f"{source['type']}_{source['name']}"
        )
        
        # Discover jobs
        discovered_jobs = collector.discover_jobs()
        logger.info(f"Discovered {len(discovered_jobs)} jobs from {source['name']}")
        
        # Sync to database
        new_count = 0
        updated_count = 0
        
        with get_session() as session:
            for job_info in discovered_jobs:
                existing = session.query(Job).filter(
                    Job.source_id == source['id'],
                    Job.external_id == job_info.full_name
                ).first()
                
                if existing:
                    # Update existing job
                    existing.name = job_info.name
                    existing.url = job_info.url
                    existing.is_active = job_info.buildable
                    existing.metadata = job_info.metadata
                    updated_count += 1
                else:
                    # Create new job
                    new_job = Job(
                        source_id=source['id'],
                        external_id=job_info.full_name,
                        name=job_info.name,
                        url=job_info.url,
                        is_active=job_info.buildable,
                        metadata=job_info.metadata
                    )
                    session.add(new_job)
                    new_count += 1
            
            session.commit()
        
        return {
            'source': source['name'],
            'discovered': len(discovered_jobs),
            'new': new_count,
            'updated': updated_count
        }
    
    @task
    def summarize_discovery(results: list) -> dict:
        """Summarize discovery results."""
        total_discovered = sum(r['discovered'] for r in results)
        total_new = sum(r['new'] for r in results)
        total_updated = sum(r['updated'] for r in results)
        
        summary = {
            'sources_processed': len(results),
            'total_jobs_discovered': total_discovered,
            'new_jobs': total_new,
            'updated_jobs': total_updated
        }
        
        # Log summary
        import logging
        logging.getLogger(__name__).info(f"Discovery summary: {summary}")
        
        return summary
    
    # DAG flow
    sources = get_active_sources()
    discovery_results = discover_jobs_for_source.expand(source=sources)
    summarize_discovery(discovery_results)
```

### 4.2 Collect Builds DAG

```python
# dags/collect_builds.py
"""
DAG to collect new builds from CI jobs.
Runs every 15 minutes to fetch new builds and their logs/artifacts.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task, task_group
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.utils.task_group import TaskGroup

default_args = {
    'owner': 'ci-harvester',
    'depends_on_past': False,
    'email_on_failure': True,
    'retries': 2,
    'retry_delay': timedelta(minutes=2),
    'execution_timeout': timedelta(minutes=45),
}

with DAG(
    dag_id='collect_builds',
    default_args=default_args,
    description='Collect new builds, logs, and artifacts',
    schedule_interval='*/15 * * * *',  # Every 15 minutes
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ci-harvester', 'collection'],
) as dag:
    
    @task
    def get_jobs_to_collect() -> list:
        """
        Get list of jobs that need collection.
        Prioritizes jobs with older last_collected timestamps.
        """
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job, CISource
        from sqlalchemy import and_
        
        with get_session() as session:
            jobs = session.query(Job).join(CISource).filter(
                and_(
                    Job.is_active == True,
                    CISource.is_active == True
                )
            ).order_by(
                Job.last_collected.asc().nullsfirst()
            ).limit(50).all()  # Process up to 50 jobs per run
            
            return [
                {
                    'id': str(j.id),
                    'external_id': j.external_id,
                    'source_id': str(j.source_id),
                    'source_type': j.source.type,
                    'source_name': j.source.name,
                    'last_collected': j.last_collected.isoformat() if j.last_collected else None
                }
                for j in jobs
            ]
    
    @task(max_active_tis_per_dag=10)  # Limit concurrent collections
    def collect_job_builds(job: dict) -> dict:
        """Collect new builds for a single job."""
        from ci_harvester.collectors import get_collector
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job, Build, BuildLog, Artifact
        from datetime import datetime, timezone
        import logging
        
        logger = logging.getLogger(__name__)
        
        collector = get_collector(
            source_type=job['source_type'],
            connection_id=f"{job['source_type']}_{job['source_name']}"
        )
        
        # Determine since when to collect
        since_time = None
        if job['last_collected']:
            since_time = datetime.fromisoformat(job['last_collected'])
        
        # Get new builds
        builds = collector.get_builds(
            job_name=job['external_id'],
            since_time=since_time,
            limit=20  # Max builds per collection
        )
        
        logger.info(f"Found {len(builds)} new builds for {job['external_id']}")
        
        builds_collected = []
        
        with get_session() as session:
            for build_info in builds:
                # Skip if build already exists
                existing = session.query(Build).filter(
                    Build.job_id == job['id'],
                    Build.external_id == str(build_info.number)
                ).first()
                
                if existing:
                    continue
                
                # Create build record
                build = Build(
                    job_id=job['id'],
                    external_id=str(build_info.number),
                    number=build_info.number,
                    status='completed' if not build_info.building else 'running',
                    result=build_info.result.lower() if build_info.result else None,
                    started_at=datetime.fromtimestamp(
                        build_info.timestamp / 1000, 
                        tz=timezone.utc
                    ) if build_info.timestamp else None,
                    duration_ms=build_info.duration,
                    metadata={
                        'executor': build_info.executor,
                        'causes': build_info.causes,
                        'parameters': build_info.parameters
                    }
                )
                session.add(build)
                session.flush()  # Get build ID
                
                # Collect console log
                try:
                    log_content = collector.get_console_log(
                        job['external_id'], 
                        build_info.number
                    )
                    build_log = BuildLog(
                        build_id=build.id,
                        log_type='console',
                        content=log_content,
                        size_bytes=len(log_content.encode('utf-8'))
                    )
                    session.add(build_log)
                except Exception as e:
                    logger.warning(f"Failed to get log for build {build_info.number}: {e}")
                
                # Collect artifacts
                try:
                    artifacts = collector.get_artifacts(
                        job['external_id'], 
                        build_info.number
                    )
                    for art_info in artifacts:
                        artifact = Artifact(
                            build_id=build.id,
                            name=art_info.file_name,
                            path=art_info.relative_path,
                            size_bytes=art_info.size,
                            metadata={'download_url': art_info.download_url}
                        )
                        session.add(artifact)
                except Exception as e:
                    logger.warning(f"Failed to get artifacts for build {build_info.number}: {e}")
                
                builds_collected.append({
                    'id': str(build.id),
                    'number': build_info.number,
                    'has_artifacts': len(artifacts) > 0 if 'artifacts' in dir() else False
                })
            
            # Update job's last_collected timestamp
            job_record = session.query(Job).get(job['id'])
            job_record.last_collected = datetime.now(timezone.utc)
            
            session.commit()
        
        return {
            'job_id': job['id'],
            'job_name': job['external_id'],
            'builds_collected': len(builds_collected),
            'builds': builds_collected
        }
    
    @task
    def trigger_test_parsing(collection_results: list):
        """Trigger test parsing for builds with artifacts."""
        from airflow.api.common.trigger_dag import trigger_dag
        
        for result in collection_results:
            for build in result.get('builds', []):
                if build.get('has_artifacts'):
                    trigger_dag(
                        dag_id='parse_test_results',
                        conf={'build_id': build['id']},
                        execution_date=None,
                        replace_microseconds=False
                    )
    
    @task
    def log_collection_summary(results: list):
        """Log collection summary."""
        import logging
        
        total_builds = sum(r['builds_collected'] for r in results)
        jobs_with_builds = sum(1 for r in results if r['builds_collected'] > 0)
        
        logging.getLogger(__name__).info(
            f"Collection complete: {total_builds} builds from "
            f"{jobs_with_builds}/{len(results)} jobs"
        )
        
        return {
            'jobs_processed': len(results),
            'jobs_with_new_builds': jobs_with_builds,
            'total_builds_collected': total_builds
        }
    
    # DAG flow
    jobs = get_jobs_to_collect()
    collection_results = collect_job_builds.expand(job=jobs)
    trigger_test_parsing(collection_results)
    log_collection_summary(collection_results)
```

### 4.3 Parse Test Results DAG

```python
# dags/parse_test_results.py
"""
DAG to parse test results from build artifacts.
Triggered by collect_builds DAG when artifacts are found.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task
from airflow.models.param import Param

default_args = {
    'owner': 'ci-harvester',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=1),
    'execution_timeout': timedelta(minutes=15),
}

with DAG(
    dag_id='parse_test_results',
    default_args=default_args,
    description='Parse test results from build artifacts',
    schedule_interval=None,  # Triggered only
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=10,
    tags=['ci-harvester', 'parsing'],
    params={
        'build_id': Param(
            default=None,
            type=['string', 'null'],
            description='Build ID to parse test results for'
        )
    },
) as dag:
    
    @task
    def get_build_artifacts(build_id: str) -> list:
        """Get list of artifacts that may contain test results."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Artifact
        
        # Patterns that indicate test result files
        TEST_RESULT_PATTERNS = [
            'Test.xml',
            'test-results.xml',
            '*_test_results.xml',
            'junit*.xml',
            'ctest*.xml'
        ]
        
        with get_session() as session:
            artifacts = session.query(Artifact).filter(
                Artifact.build_id == build_id,
                Artifact.is_test_result == False  # Not yet parsed
            ).all()
            
            # Filter to likely test result files
            import fnmatch
            result_artifacts = []
            for artifact in artifacts:
                for pattern in TEST_RESULT_PATTERNS:
                    if fnmatch.fnmatch(artifact.name, pattern):
                        result_artifacts.append({
                            'id': str(artifact.id),
                            'name': artifact.name,
                            'path': artifact.path,
                            'download_url': artifact.metadata.get('download_url')
                        })
                        break
            
            return result_artifacts
    
    @task
    def download_and_parse_artifact(artifact: dict, build_id: str) -> dict:
        """Download artifact and parse test results."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Artifact, Build
        from ci_harvester.parsers import ParserFactory
        from ci_harvester.parsers.ctest import CTestResultSaver
        from ci_harvester.collectors import get_collector_for_build
        import logging
        
        logger = logging.getLogger(__name__)
        
        with get_session() as session:
            build = session.query(Build).get(build_id)
            if not build:
                raise ValueError(f"Build {build_id} not found")
            
            # Get collector to download artifact
            collector = get_collector_for_build(build)
            
            # Download artifact content
            content = collector.download_artifact_by_url(artifact['download_url'])
            
            # Parse test results
            factory = ParserFactory()
            try:
                report = factory.parse(content, artifact['name'])
                logger.info(
                    f"Parsed {report.total_tests} tests from {artifact['name']}"
                )
                
                # Save to database
                saver = CTestResultSaver(session)
                saved_count = saver.save(report, build)
                
                # Mark artifact as parsed
                artifact_record = session.query(Artifact).get(artifact['id'])
                artifact_record.is_test_result = True
                
                session.commit()
                
                return {
                    'artifact': artifact['name'],
                    'tests_parsed': report.total_tests,
                    'tests_saved': saved_count,
                    'passed': report.total_passed,
                    'failed': report.total_failed
                }
                
            except ValueError as e:
                logger.warning(f"Could not parse {artifact['name']}: {e}")
                return {
                    'artifact': artifact['name'],
                    'error': str(e),
                    'tests_parsed': 0
                }
    
    @task
    def summarize_parsing(results: list, build_id: str) -> dict:
        """Summarize parsing results."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Build
        import logging
        
        total_tests = sum(r.get('tests_saved', 0) for r in results)
        total_passed = sum(r.get('passed', 0) for r in results)
        total_failed = sum(r.get('failed', 0) for r in results)
        errors = [r for r in results if 'error' in r]
        
        summary = {
            'build_id': build_id,
            'artifacts_processed': len(results),
            'artifacts_with_errors': len(errors),
            'total_tests': total_tests,
            'passed': total_passed,
            'failed': total_failed
        }
        
        logging.getLogger(__name__).info(f"Parse summary for build {build_id}: {summary}")
        
        # Update build metadata with test summary
        with get_session() as session:
            build = session.query(Build).get(build_id)
            if build:
                build.metadata = {
                    **build.metadata,
                    'test_summary': summary
                }
                session.commit()
        
        return summary
    
    # DAG flow
    build_id = "{{ params.build_id or dag_run.conf.get('build_id') }}"
    artifacts = get_build_artifacts(build_id=build_id)
    parse_results = download_and_parse_artifact.partial(build_id=build_id).expand(
        artifact=artifacts
    )
    summarize_parsing(results=parse_results, build_id=build_id)
```

### 4.4 Cleanup DAG

```python
# dags/cleanup_old_data.py
"""
DAG to clean up old data based on retention policies.
Runs daily at 2 AM.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable

default_args = {
    'owner': 'ci-harvester',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(hours=2),
}

# Retention periods (in days)
RETENTION_CONFIG = {
    'test_results': 365,  # 1 year
    'build_logs': 90,     # 3 months
    'builds': 730,        # 2 years
    'collection_runs': 30 # 1 month
}

with DAG(
    dag_id='cleanup_old_data',
    default_args=default_args,
    description='Clean up old data based on retention policies',
    schedule_interval='0 2 * * *',  # Daily at 2 AM
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ci-harvester', 'maintenance'],
) as dag:
    
    @task
    def cleanup_test_results() -> dict:
        """Remove old test results."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import TestResult
        from datetime import datetime, timezone
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=RETENTION_CONFIG['test_results']
        )
        
        with get_session() as session:
            deleted = session.query(TestResult).filter(
                TestResult.created_at < cutoff_date
            ).delete(synchronize_session=False)
            session.commit()
        
        return {'deleted_test_results': deleted}
    
    @task
    def cleanup_build_logs() -> dict:
        """Remove old build logs."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import BuildLog
        from datetime import datetime, timezone
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=RETENTION_CONFIG['build_logs']
        )
        
        with get_session() as session:
            deleted = session.query(BuildLog).filter(
                BuildLog.created_at < cutoff_date
            ).delete(synchronize_session=False)
            session.commit()
        
        return {'deleted_build_logs': deleted}
    
    @task
    def cleanup_collection_runs() -> dict:
        """Remove old collection run records."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import CollectionRun
        from datetime import datetime, timezone
        
        cutoff_date = datetime.now(timezone.utc) - timedelta(
            days=RETENTION_CONFIG['collection_runs']
        )
        
        with get_session() as session:
            deleted = session.query(CollectionRun).filter(
                CollectionRun.created_at < cutoff_date
            ).delete(synchronize_session=False)
            session.commit()
        
        return {'deleted_collection_runs': deleted}
    
    @task
    def vacuum_database():
        """Run VACUUM ANALYZE on heavily used tables."""
        from ci_harvester.db import get_engine
        
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute("VACUUM ANALYZE test_results")
            conn.execute("VACUUM ANALYZE build_logs")
            conn.execute("VACUUM ANALYZE builds")
        
        return {'vacuum': 'completed'}
    
    @task
    def summarize_cleanup(results: list) -> dict:
        """Summarize cleanup results."""
        import logging
        
        summary = {}
        for result in results:
            summary.update(result)
        
        logging.getLogger(__name__).info(f"Cleanup summary: {summary}")
        return summary
    
    # DAG flow - run cleanup tasks in parallel
    results = [
        cleanup_test_results(),
        cleanup_build_logs(),
        cleanup_collection_runs()
    ]
    vacuum_database()
    summarize_cleanup(results)
```

### 4.5 Health Check DAG

```python
# dags/health_check.py
"""
DAG to monitor system health.
Runs every 5 minutes.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task
from airflow.operators.python import BranchPythonOperator

default_args = {
    'owner': 'ci-harvester',
    'depends_on_past': False,
    'retries': 0,
    'execution_timeout': timedelta(minutes=5),
}

with DAG(
    dag_id='health_check',
    default_args=default_args,
    description='Monitor system health',
    schedule_interval='*/5 * * * *',
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ci-harvester', 'monitoring'],
) as dag:
    
    @task
    def check_database_connection() -> dict:
        """Verify database connectivity."""
        from ci_harvester.db import get_session
        
        try:
            with get_session() as session:
                session.execute("SELECT 1")
            return {'database': 'healthy', 'error': None}
        except Exception as e:
            return {'database': 'unhealthy', 'error': str(e)}
    
    @task
    def check_ci_sources() -> dict:
        """Check connectivity to CI sources."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import CISource
        from ci_harvester.collectors import get_collector
        
        results = []
        
        with get_session() as session:
            sources = session.query(CISource).filter(
                CISource.is_active == True
            ).all()
            
            for source in sources:
                try:
                    collector = get_collector(
                        source_type=source.type,
                        connection_id=f"{source.type}_{source.name}"
                    )
                    collector.test_connection()
                    results.append({
                        'source': source.name,
                        'status': 'healthy'
                    })
                except Exception as e:
                    results.append({
                        'source': source.name,
                        'status': 'unhealthy',
                        'error': str(e)
                    })
        
        return {'ci_sources': results}
    
    @task
    def check_collection_freshness() -> dict:
        """Check if collections are running on schedule."""
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job
        from datetime import datetime, timezone
        
        stale_threshold = timedelta(hours=2)
        now = datetime.now(timezone.utc)
        
        with get_session() as session:
            stale_jobs = session.query(Job).filter(
                Job.is_active == True,
                Job.last_collected < now - stale_threshold
            ).count()
            
            total_jobs = session.query(Job).filter(
                Job.is_active == True
            ).count()
        
        return {
            'total_active_jobs': total_jobs,
            'stale_jobs': stale_jobs,
            'freshness': 'healthy' if stale_jobs == 0 else 'warning'
        }
    
    @task
    def aggregate_health(db_status, sources_status, freshness_status) -> dict:
        """Aggregate health check results."""
        import logging
        
        all_healthy = (
            db_status.get('database') == 'healthy' and
            all(s['status'] == 'healthy' for s in sources_status.get('ci_sources', [])) and
            freshness_status.get('freshness') == 'healthy'
        )
        
        status = {
            'overall': 'healthy' if all_healthy else 'unhealthy',
            'database': db_status,
            'ci_sources': sources_status,
            'collection_freshness': freshness_status,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        logger = logging.getLogger(__name__)
        if all_healthy:
            logger.info(f"Health check passed: {status}")
        else:
            logger.warning(f"Health check failed: {status}")
        
        return status
    
    @task
    def send_alert_if_unhealthy(health_status: dict):
        """Send alert if system is unhealthy."""
        if health_status['overall'] != 'healthy':
            # Send alert (implement based on your alerting system)
            # Examples: PagerDuty, Slack, email
            from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator
            # Or use Variable.get('alerting_webhook')
            pass
    
    # DAG flow
    db_status = check_database_connection()
    sources_status = check_ci_sources()
    freshness_status = check_collection_freshness()
    health = aggregate_health(db_status, sources_status, freshness_status)
    send_alert_if_unhealthy(health)
```

## 5. Airflow Configuration

### 5.1 airflow.cfg Settings

```ini
[core]
dags_folder = /opt/airflow/dags
executor = CeleryExecutor  # Or LocalExecutor for dev
parallelism = 32
dag_concurrency = 16
max_active_runs_per_dag = 3

[scheduler]
min_file_process_interval = 30
dag_dir_list_interval = 60

[webserver]
web_server_port = 8080
workers = 4

[celery]
broker_url = redis://redis:6379/0
result_backend = db+postgresql://airflow:airflow@postgres/airflow
worker_concurrency = 8

[logging]
base_log_folder = /opt/airflow/logs
remote_logging = True
remote_base_log_folder = s3://my-bucket/airflow-logs
```

### 5.2 Connections Setup

```python
# Setup script for Airflow connections
from airflow.models import Connection
from airflow import settings

def setup_connections():
    session = settings.Session()
    
    # PostgreSQL connection for CI Harvester data
    ci_harvester_db = Connection(
        conn_id='ci_harvester_db',
        conn_type='postgres',
        host='postgres',
        port=5432,
        login='ci_harvester',
        password='secret',
        schema='ci_harvester'
    )
    session.merge(ci_harvester_db)
    
    # Jenkins connection
    jenkins_main = Connection(
        conn_id='jenkins_main',
        conn_type='http',
        host='jenkins.example.com',
        port=443,
        login='ci-harvester',
        password='api-token',
        schema='https',
        extra='{"verify_ssl": true}'
    )
    session.merge(jenkins_main)
    
    session.commit()
```

### 5.3 Variables

```python
# Airflow Variables for CI Harvester
VARIABLES = {
    'ci_harvester_retention_days': 365,
    'ci_harvester_max_builds_per_collection': 20,
    'ci_harvester_parallel_collections': 10,
    'ci_harvester_alert_email': 'team@example.com',
}
```

## 6. Monitoring & Alerting

### 6.1 DAG-Level Alerts

```python
# Email on failure
default_args = {
    'email': ['team@example.com'],
    'email_on_failure': True,
    'email_on_retry': False,
}
```

### 6.2 Custom Alerting

```python
from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator

def on_failure_callback(context):
    """Send Slack alert on task failure."""
    slack_msg = f"""
:red_circle: Task Failed
*DAG*: {context['dag'].dag_id}
*Task*: {context['task'].task_id}
*Execution Time*: {context['execution_date']}
*Error*: {context['exception']}
"""
    
    slack_alert = SlackWebhookOperator(
        task_id='slack_alert',
        webhook_token=Variable.get('slack_webhook'),
        message=slack_msg
    )
    return slack_alert.execute(context=context)

default_args = {
    'on_failure_callback': on_failure_callback
}
```

### 6.3 Metrics Export

```python
# Export metrics to Prometheus/StatsD
from airflow.configuration import conf
from statsd import StatsClient

statsd = StatsClient(
    host=conf.get('metrics', 'statsd_host'),
    port=conf.get('metrics', 'statsd_port'),
    prefix='airflow.ci_harvester'
)

# In tasks:
statsd.incr('builds_collected')
statsd.gauge('tests_parsed', count)
statsd.timing('collection_duration', duration_ms)
```

## 7. Deployment

### 7.1 Docker Compose (Development)

```yaml
# docker-compose.airflow.yml
version: '3.8'

x-airflow-common:
  &airflow-common
  image: apache/airflow:2.7.0-python3.10
  environment:
    &airflow-common-env
    AIRFLOW__CORE__EXECUTOR: LocalExecutor
    AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
    AIRFLOW__CORE__FERNET_KEY: ''
    AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION: 'false'
    AIRFLOW__CORE__LOAD_EXAMPLES: 'false'
  volumes:
    - ./dags:/opt/airflow/dags
    - ./ci_harvester:/opt/airflow/ci_harvester
    - ./logs:/opt/airflow/logs
  depends_on:
    - postgres

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: airflow
      POSTGRES_DB: airflow
    volumes:
      - postgres-data:/var/lib/postgresql/data

  airflow-init:
    <<: *airflow-common
    entrypoint: /bin/bash
    command:
      - -c
      - airflow db init && airflow users create --username admin --password admin --firstname Admin --lastname User --role Admin --email admin@example.com

  airflow-webserver:
    <<: *airflow-common
    command: webserver
    ports:
      - "8080:8080"

  airflow-scheduler:
    <<: *airflow-common
    command: scheduler

volumes:
  postgres-data:
```

### 7.2 Kubernetes (Production)

Use the official Airflow Helm chart:

```bash
helm repo add apache-airflow https://airflow.apache.org
helm install airflow apache-airflow/airflow \
  --namespace airflow \
  --values airflow-values.yaml
```

```yaml
# airflow-values.yaml
executor: "CeleryExecutor"

images:
  airflow:
    repository: my-registry/ci-harvester-airflow
    tag: latest

dags:
  gitSync:
    enabled: true
    repo: git@github.com:org/ci-harvester.git
    branch: main
    subPath: dags

workers:
  replicas: 3

redis:
  enabled: true

postgresql:
  enabled: false  # Use external PostgreSQL

data:
  metadataConnection:
    host: my-rds-instance.amazonaws.com
```
