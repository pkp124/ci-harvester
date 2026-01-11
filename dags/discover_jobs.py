"""
DAG to discover CI jobs from configured sources.

Runs hourly to find new or changed jobs.
See docs/design/AIRFLOW_WORKFLOWS.md for detailed documentation.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task

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
                    existing.name = job_info.name
                    existing.url = job_info.url
                    existing.is_active = job_info.buildable
                    existing.metadata = job_info.metadata
                    updated_count += 1
                else:
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
        import logging
        
        total_discovered = sum(r['discovered'] for r in results)
        total_new = sum(r['new'] for r in results)
        total_updated = sum(r['updated'] for r in results)
        
        summary = {
            'sources_processed': len(results),
            'total_jobs_discovered': total_discovered,
            'new_jobs': total_new,
            'updated_jobs': total_updated
        }
        
        logging.getLogger(__name__).info(f"Discovery summary: {summary}")
        return summary
    
    # DAG flow
    sources = get_active_sources()
    discovery_results = discover_jobs_for_source.expand(source=sources)
    summarize_discovery(discovery_results)
