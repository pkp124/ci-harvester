"""
DAG: Discover Jobs

Discovers CI jobs from configured sources.
Runs every 10 minutes by default (configurable via Airflow Variable).

Variables:
  - discovery_schedule: Cron expression (default: "*/10 * * * *")
  - discovery_enabled: Enable/disable discovery (default: true)

See docs/design/SCHEDULING_POLICY.md for configuration details.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task
from airflow.models import Variable

# =============================================================================
# DAG Definition
# =============================================================================

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
    # Schedule from Airflow Variable (default: every 10 minutes)
    schedule_interval=Variable.get('discovery_schedule', '*/10 * * * *'),
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
                    'url': s.url,
                    'connection_id': s.connection_id,
                    'config': s.config
                }
                for s in sources
            ]
    
    @task
    def discover_jobs_for_source(source: dict) -> dict:
        """Discover jobs for a single source using configuration."""
        from ci_harvester.collectors import get_collector
        from ci_harvester.config import Config
        from ci_harvester.db import get_session
        from ci_harvester.db.models import Job, Product
        import re
        import structlog
        
        logger = structlog.get_logger()
        config = Config.get()
        
        logger.info("discovering_jobs", source=source['name'], type=source['type'])
        
        # Get collector for source type
        collector = get_collector(
            source_type=source['type'],
            connection_id=source.get('connection_id', f"{source['type']}_default")
        )
        
        # Get discovery configuration
        discovery_config = source.get('config', {}).get('discovery', {})
        include_patterns = discovery_config.get('include_patterns', ['.*'])
        exclude_patterns = discovery_config.get('exclude_patterns', [])
        
        # Discover jobs from CI platform
        try:
            discovered_jobs = collector.discover_jobs()
        except Exception as e:
            logger.error("discovery_failed", source=source['name'], error=str(e))
            return {
                'source': source['name'],
                'error': str(e),
                'discovered': 0,
                'new': 0,
                'updated': 0
            }
        
        logger.info("jobs_found", source=source['name'], count=len(discovered_jobs))
        
        # Filter jobs based on patterns
        filtered_jobs = []
        for job_info in discovered_jobs:
            job_name = job_info.full_name
            
            # Check excludes first
            excluded = False
            for pattern in exclude_patterns:
                if re.match(pattern, job_name):
                    excluded = True
                    break
            
            if excluded:
                continue
            
            # Check includes
            for pattern in include_patterns:
                if re.match(pattern, job_name):
                    filtered_jobs.append(job_info)
                    break
        
        logger.info("jobs_filtered", 
            source=source['name'], 
            before=len(discovered_jobs),
            after=len(filtered_jobs))
        
        # Sync to database
        new_count = 0
        updated_count = 0
        
        with get_session() as session:
            for job_info in filtered_jobs:
                # Find which product this job belongs to
                product_name = config.find_product_for_job(
                    job_info.full_name, 
                    source['name']
                )
                
                product_id = None
                if product_name:
                    product = session.query(Product).filter(
                        Product.name == product_name
                    ).first()
                    if product:
                        product_id = product.id
                
                # Check if job exists
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
                    if product_id:
                        existing.product_id = product_id
                    updated_count += 1
                else:
                    # Create new job
                    if product_id is None:
                        # Create a default product if none matched
                        default_product = session.query(Product).filter(
                            Product.name == 'Unassigned'
                        ).first()
                        if not default_product:
                            default_product = Product(
                                name='Unassigned',
                                description='Jobs not assigned to a product'
                            )
                            session.add(default_product)
                            session.flush()
                        product_id = default_product.id
                    
                    new_job = Job(
                        source_id=source['id'],
                        product_id=product_id,
                        external_id=job_info.full_name,
                        name=job_info.name,
                        url=job_info.url,
                        is_active=job_info.buildable,
                        metadata=job_info.metadata
                    )
                    session.add(new_job)
                    new_count += 1
            
            session.commit()
        
        logger.info("discovery_complete",
            source=source['name'],
            discovered=len(filtered_jobs),
            new=new_count,
            updated=updated_count)
        
        return {
            'source': source['name'],
            'discovered': len(filtered_jobs),
            'new': new_count,
            'updated': updated_count
        }
    
    @task
    def summarize_discovery(results: list) -> dict:
        """Summarize discovery results."""
        import structlog
        
        logger = structlog.get_logger()
        
        successful = [r for r in results if 'error' not in r]
        errors = [r for r in results if 'error' in r]
        
        total_discovered = sum(r.get('discovered', 0) for r in successful)
        total_new = sum(r.get('new', 0) for r in successful)
        total_updated = sum(r.get('updated', 0) for r in successful)
        
        summary = {
            'sources_processed': len(results),
            'sources_succeeded': len(successful),
            'sources_failed': len(errors),
            'total_jobs_discovered': total_discovered,
            'new_jobs': total_new,
            'updated_jobs': total_updated
        }
        
        logger.info("discovery_summary", **summary)
        
        if errors:
            for err in errors:
                logger.warning("source_error", 
                    source=err['source'], 
                    error=err.get('error'))
        
        return summary
    
    # =========================================================================
    # DAG Flow
    # =========================================================================
    
    sources = get_active_sources()
    discovery_results = discover_jobs_for_source.expand(source=sources)
    summarize_discovery(discovery_results)
