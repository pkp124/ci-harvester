"""
Bootstrap script to initialize CI Harvester configuration.

This script:
1. Loads configuration from YAML file
2. Creates CI sources in the database
3. Creates products in the database
4. Optionally triggers initial job discovery

Usage:
    python -m ci_harvester.config.bootstrap
    python -m ci_harvester.config.bootstrap --config /path/to/config.yaml
    python -m ci_harvester.config.bootstrap --discover  # Also run discovery
"""

import argparse
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger()


def bootstrap_database(config_path: str = None, discover: bool = False):
    """
    Bootstrap the database with configuration from YAML file.
    
    Args:
        config_path: Path to configuration file
        discover: If True, also trigger job discovery
    """
    from ci_harvester.config import Config
    from ci_harvester.db import get_session
    from ci_harvester.db.models import CISource, Product
    
    # Load configuration
    config = Config.load(config_path)
    
    logger.info("bootstrap_starting", config_path=config_path)
    
    with get_session() as session:
        # Create CI Sources
        sources_created = 0
        sources_updated = 0
        
        for source_config in config.get_ci_sources():
            existing = session.query(CISource).filter(
                CISource.name == source_config.name
            ).first()
            
            if existing:
                # Update existing
                existing.type = source_config.type
                existing.url = source_config.url
                existing.connection_id = source_config.connection_id
                existing.config = {
                    'discovery': {
                        'include_patterns': source_config.include_patterns,
                        'exclude_patterns': source_config.exclude_patterns,
                        'folder_depth': source_config.folder_depth,
                    },
                    'defaults': {
                        'collect_logs': source_config.collect_logs,
                        'max_log_size_mb': source_config.max_log_size_mb,
                        'artifact_patterns': source_config.artifact_patterns,
                    }
                }
                existing.is_active = True
                sources_updated += 1
                logger.info("source_updated", name=source_config.name)
            else:
                # Create new
                new_source = CISource(
                    name=source_config.name,
                    type=source_config.type,
                    url=source_config.url,
                    connection_id=source_config.connection_id,
                    config={
                        'discovery': {
                            'include_patterns': source_config.include_patterns,
                            'exclude_patterns': source_config.exclude_patterns,
                            'folder_depth': source_config.folder_depth,
                        },
                        'defaults': {
                            'collect_logs': source_config.collect_logs,
                            'max_log_size_mb': source_config.max_log_size_mb,
                            'artifact_patterns': source_config.artifact_patterns,
                        }
                    },
                    is_active=True
                )
                session.add(new_source)
                sources_created += 1
                logger.info("source_created", name=source_config.name)
        
        # Create Products
        products_created = 0
        products_updated = 0
        
        for product_config in config.get_products():
            existing = session.query(Product).filter(
                Product.name == product_config.name
            ).first()
            
            if existing:
                # Update existing
                existing.description = product_config.description
                existing.repository_url = product_config.repository_url
                existing.config = {
                    'job_patterns': product_config.job_patterns,
                    'settings': {
                        'priority': product_config.priority,
                        'collect_logs': product_config.collect_logs,
                        'max_builds_per_collection': product_config.max_builds_per_collection,
                    }
                }
                existing.is_active = True
                products_updated += 1
                logger.info("product_updated", name=product_config.name)
            else:
                # Create new
                new_product = Product(
                    name=product_config.name,
                    description=product_config.description,
                    repository_url=product_config.repository_url,
                    config={
                        'job_patterns': product_config.job_patterns,
                        'settings': {
                            'priority': product_config.priority,
                            'collect_logs': product_config.collect_logs,
                            'max_builds_per_collection': product_config.max_builds_per_collection,
                        }
                    },
                    is_active=True
                )
                session.add(new_product)
                products_created += 1
                logger.info("product_created", name=product_config.name)
        
        # Create default "Unassigned" product if it doesn't exist
        unassigned = session.query(Product).filter(
            Product.name == 'Unassigned'
        ).first()
        if not unassigned:
            session.add(Product(
                name='Unassigned',
                description='Jobs not assigned to a specific product'
            ))
            products_created += 1
            logger.info("product_created", name='Unassigned')
        
        session.commit()
        
        logger.info("bootstrap_complete",
            sources_created=sources_created,
            sources_updated=sources_updated,
            products_created=products_created,
            products_updated=products_updated)
    
    # Optionally trigger discovery
    if discover:
        trigger_discovery()
    
    return {
        'sources_created': sources_created,
        'sources_updated': sources_updated,
        'products_created': products_created,
        'products_updated': products_updated,
    }


def trigger_discovery():
    """Trigger Airflow DAG to discover jobs."""
    try:
        from airflow.api.common.trigger_dag import trigger_dag
        
        logger.info("triggering_discovery")
        trigger_dag(
            dag_id='discover_jobs',
            conf={},
            execution_date=None,
            replace_microseconds=False
        )
        logger.info("discovery_triggered")
    except ImportError:
        logger.warning("airflow_not_available", 
            message="Run 'airflow dags trigger discover_jobs' manually")
    except Exception as e:
        logger.error("discovery_trigger_failed", error=str(e))


def create_tables():
    """Create database tables if they don't exist."""
    from ci_harvester.db import get_engine
    from ci_harvester.db.models import Base
    
    logger.info("creating_tables")
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("tables_created")


def main():
    """Main entry point for bootstrap script."""
    parser = argparse.ArgumentParser(
        description='Bootstrap CI Harvester configuration'
    )
    parser.add_argument(
        '--config', '-c',
        help='Path to configuration YAML file',
        default=None
    )
    parser.add_argument(
        '--discover', '-d',
        action='store_true',
        help='Trigger job discovery after bootstrap'
    )
    parser.add_argument(
        '--create-tables',
        action='store_true',
        help='Create database tables before bootstrap'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    
    try:
        if args.create_tables:
            create_tables()
        
        result = bootstrap_database(
            config_path=args.config,
            discover=args.discover
        )
        
        print("\n✅ Bootstrap complete!")
        print(f"   CI Sources: {result['sources_created']} created, {result['sources_updated']} updated")
        print(f"   Products: {result['products_created']} created, {result['products_updated']} updated")
        
        if not args.discover:
            print("\n💡 Next steps:")
            print("   1. Add Jenkins credentials to Airflow:")
            print("      airflow connections add jenkins_main --conn-type http ...")
            print("   2. Enable DAGs:")
            print("      airflow dags unpause discover_jobs")
            print("      airflow dags unpause collect_builds")
            print("   3. Trigger initial discovery:")
            print("      airflow dags trigger discover_jobs")
        
    except Exception as e:
        logger.error("bootstrap_failed", error=str(e))
        print(f"\n❌ Bootstrap failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
