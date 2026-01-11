"""
DAG: Collect Builds

Collects new builds from CI jobs every N minutes.
All configuration via Airflow Variables - no custom scheduling code needed.

Variables:
  - collection_schedule: Cron expression (default: "*/5 * * * *")
  - max_jobs_per_run: Max jobs to process (default: 50)
  - max_builds_per_job: Max builds per job (default: 20)
  - max_parallel_jobs: Concurrent job collections (default: 10)
  - jenkins_rate_limit: Requests/min to Jenkins (default: 100)
"""

from datetime import datetime, timedelta, timezone
from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable

# =============================================================================
# Configuration from Airflow Variables
# =============================================================================

def get_config():
    """Load configuration from Airflow Variables."""
    return {
        'max_jobs_per_run': int(Variable.get('max_jobs_per_run', 50)),
        'max_builds_per_job': int(Variable.get('max_builds_per_job', 20)),
        'max_parallel_jobs': int(Variable.get('max_parallel_jobs', 10)),
        'collect_logs': Variable.get('collect_logs', 'true').lower() == 'true',
        'parse_results': Variable.get('parse_results', 'true').lower() == 'true',
    }

# =============================================================================
# DAG Definition
# =============================================================================

default_args = {
    'owner': 'ci-harvester',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=2),
    'execution_timeout': timedelta(minutes=30),
}

with DAG(
    dag_id='collect_builds',
    default_args=default_args,
    description='Collect new builds from CI jobs',
    # Schedule from Variable, default every 5 minutes
    schedule_interval=Variable.get('collection_schedule', '*/5 * * * *'),
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ci-harvester', 'collection'],
) as dag:
    
    @task
    def get_jobs_to_collect() -> list:
        """
        Get jobs due for collection, oldest first.
        
        Simple priority: jobs that haven't been collected recently
        get processed first. No complex priority system needed.
        """
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job, Product
        
        config = get_config()
        
        with get_session() as session:
            jobs = session.query(Job).join(Product).filter(
                Job.is_active == True,
                Product.is_active == True
            ).order_by(
                # Priority: never collected first, then oldest
                Job.last_collected.asc().nullsfirst()
            ).limit(
                config['max_jobs_per_run']
            ).all()
            
            return [
                {
                    'id': str(j.id),
                    'name': j.name,
                    'external_id': j.external_id,
                    'ci_source': j.ci_source,
                    'product_name': j.product.name,
                }
                for j in jobs
            ]
    
    @task(max_active_tis_per_dag=10)  # Limit parallel executions
    def collect_job(job: dict) -> dict:
        """
        Collect new builds for a single job.
        
        Rate limiting is handled by the collector.
        """
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job, Build, BuildLog, Artifact
        from ci_harvester.collectors import get_collector
        from ci_harvester.utils.rate_limit import rate_limited_jenkins
        import structlog
        
        logger = structlog.get_logger()
        config = get_config()
        
        logger.info("collecting_job", job=job['name'], product=job['product_name'])
        
        # Get collector for this CI source
        collector = get_collector(
            source_type=job['ci_source'],
            connection_id=f"{job['ci_source']}_default"
        )
        
        builds_saved = 0
        
        with get_session() as session:
            db_job = session.query(Job).filter(Job.id == job['id']).first()
            if not db_job:
                return {'job': job['name'], 'error': 'Job not found'}
            
            # Get builds since last collection
            since_time = db_job.last_collected
            
            try:
                # Rate-limited API call
                builds = collector.get_builds(
                    job_name=job['external_id'],
                    since_time=since_time,
                    limit=config['max_builds_per_job']
                )
            except Exception as e:
                logger.error("collection_failed", job=job['name'], error=str(e))
                return {'job': job['name'], 'error': str(e), 'builds': 0}
            
            for build_info in builds:
                # Skip if already exists
                existing = session.query(Build).filter(
                    Build.job_id == job['id'],
                    Build.number == build_info.number
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
                        build_info.timestamp / 1000, tz=timezone.utc
                    ) if build_info.timestamp else None,
                    duration_ms=build_info.duration,
                    metadata={
                        'executor': build_info.executor,
                        'causes': build_info.causes,
                    }
                )
                session.add(build)
                session.flush()
                
                # Collect log if enabled
                if config['collect_logs']:
                    try:
                        log_content = collector.get_console_log(
                            job['external_id'], 
                            build_info.number
                        )
                        log = BuildLog(
                            build_id=build.id,
                            log_type='console',
                            content=log_content[:10_000_000],  # 10MB limit
                            size_bytes=len(log_content.encode('utf-8'))
                        )
                        session.add(log)
                    except Exception as e:
                        logger.warning("log_collection_failed", 
                            build=build_info.number, error=str(e))
                
                # Record artifacts for later parsing
                try:
                    artifacts = collector.get_artifacts(
                        job['external_id'], 
                        build_info.number
                    )
                    for art in artifacts:
                        artifact = Artifact(
                            build_id=build.id,
                            name=art.file_name,
                            path=art.relative_path,
                            is_test_result=_is_test_result(art.file_name),
                            metadata={'download_url': art.download_url}
                        )
                        session.add(artifact)
                except Exception as e:
                    logger.warning("artifact_listing_failed", 
                        build=build_info.number, error=str(e))
                
                builds_saved += 1
            
            # Update last_collected timestamp
            db_job.last_collected = datetime.now(timezone.utc)
            session.commit()
        
        logger.info("collection_complete", 
            job=job['name'], builds=builds_saved)
        
        return {
            'job': job['name'],
            'builds': builds_saved,
            'product': job['product_name']
        }
    
    @task
    def trigger_parsing(results: list):
        """Trigger test result parsing for builds with test artifacts."""
        from airflow.operators.trigger_dagrun import TriggerDagRunOperator
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Artifact, Build
        
        config = get_config()
        if not config['parse_results']:
            return
        
        with get_session() as session:
            # Find builds with unparsed test artifacts
            artifacts = session.query(Artifact).join(Build).filter(
                Artifact.is_test_result == True,
                Artifact.metadata['parsed'].astext != 'true'
            ).limit(100).all()
            
            build_ids = list(set(a.build_id for a in artifacts))
        
        # Trigger parse DAG for each build
        # In practice, you might batch these
        for build_id in build_ids:
            TriggerDagRunOperator(
                task_id=f'trigger_parse_{build_id}',
                trigger_dag_id='parse_test_results',
                conf={'build_id': str(build_id)},
            ).execute(context={})
    
    @task
    def log_summary(results: list):
        """Log collection summary."""
        import structlog
        
        logger = structlog.get_logger()
        
        total_builds = sum(r.get('builds', 0) for r in results if 'error' not in r)
        errors = [r for r in results if 'error' in r]
        
        logger.info("collection_summary",
            jobs_processed=len(results),
            total_builds=total_builds,
            errors=len(errors))
        
        return {
            'jobs_processed': len(results),
            'total_builds': total_builds,
            'errors': len(errors)
        }
    
    # =========================================================================
    # DAG Flow
    # =========================================================================
    
    jobs = get_jobs_to_collect()
    results = collect_job.expand(job=jobs)
    trigger_parsing(results)
    log_summary(results)


def _is_test_result(filename: str) -> bool:
    """Check if file is likely a test result."""
    patterns = ['Test.xml', 'test-results', 'junit', 'ctest']
    return any(p.lower() in filename.lower() for p in patterns)
