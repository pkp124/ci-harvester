"""
Job Scheduler - Determines which jobs to collect and when.

See docs/design/SCHEDULING_POLICY.md for detailed documentation.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from uuid import UUID
import structlog

from .config import SchedulingConfig, JobPriority

logger = structlog.get_logger()


@dataclass
class ScheduledJob:
    """A job scheduled for collection."""
    job_id: UUID
    job_name: str
    product_id: UUID
    product_name: str
    priority: JobPriority
    effective_priority: JobPriority
    last_collected: Optional[datetime]
    pending_builds: int
    ci_source: str
    settings: Dict[str, Any]


class JobScheduler:
    """
    Scheduler that determines which jobs to collect based on priority,
    timing, and system load.
    """
    
    def __init__(self, config: SchedulingConfig, session):
        """
        Initialize scheduler.
        
        Args:
            config: Scheduling configuration
            session: Database session
        """
        self.config = config
        self.session = session
    
    def get_pending_jobs(
        self,
        max_jobs: Optional[int] = None,
        priorities: Optional[List[JobPriority]] = None,
        product_id: Optional[UUID] = None,
    ) -> List[ScheduledJob]:
        """
        Get jobs that are due for collection.
        
        Args:
            max_jobs: Maximum jobs to return
            priorities: Filter to these priority levels
            product_id: Filter to this product
            
        Returns:
            List of jobs sorted by effective priority
        """
        from ci_harvester.db.models import Job, Product
        
        max_jobs = max_jobs or self.config.max_jobs_per_cycle
        
        # Query active jobs
        query = self.session.query(Job).join(Product).filter(
            Job.is_active == True,
            Product.is_active == True
        )
        
        if product_id:
            query = query.filter(Job.product_id == product_id)
        
        jobs = query.all()
        
        # Calculate effective priority and filter
        scheduled_jobs = []
        now = datetime.now(timezone.utc)
        
        for job in jobs:
            # Get base priority from config
            base_priority = self.config.get_job_priority(
                job_id=str(job.id),
                job_name=job.name,
                product_name=job.product.name
            )
            
            # Check if enabled
            job_settings = self.config.get_job_settings(str(job.id), job.name)
            if not job_settings.get('enabled', True):
                continue
            
            # Calculate effective priority (may be boosted)
            effective_priority = self._calculate_effective_priority(
                job, base_priority, now
            )
            
            # Filter by priority if specified
            if priorities and effective_priority not in priorities:
                continue
            
            # Check if due for collection
            if not self._is_due_for_collection(job, job_settings, now):
                continue
            
            scheduled_jobs.append(ScheduledJob(
                job_id=job.id,
                job_name=job.name,
                product_id=job.product_id,
                product_name=job.product.name,
                priority=base_priority,
                effective_priority=effective_priority,
                last_collected=job.last_collected,
                pending_builds=self._estimate_pending_builds(job),
                ci_source=job.ci_source,
                settings=job_settings,
            ))
        
        # Sort by effective priority (lower = higher priority)
        scheduled_jobs.sort(key=lambda j: (
            j.effective_priority,
            j.last_collected or datetime.min.replace(tzinfo=timezone.utc)
        ))
        
        # Limit results
        return scheduled_jobs[:max_jobs]
    
    def _calculate_effective_priority(
        self,
        job,
        base_priority: JobPriority,
        now: datetime
    ) -> JobPriority:
        """
        Calculate effective priority with dynamic adjustments.
        
        Priority may be boosted (lower number) based on:
        - Time since last collection (aging)
        - Recent failure rate
        - Pending retry status
        """
        priority = base_priority.value
        
        # Aging: boost if waiting too long
        if job.last_collected:
            wait_time = now - job.last_collected
            
            # Boost after 30 minutes
            if wait_time > timedelta(minutes=30):
                priority = max(0, priority - 1)
            
            # Further boost after 1 hour
            if wait_time > timedelta(hours=1):
                priority = max(0, priority - 1)
        else:
            # Never collected - boost priority
            priority = max(0, priority - 1)
        
        # Check recent failure rate
        failure_rate = self._get_recent_failure_rate(job)
        if failure_rate > 0.5:
            # High failure rate - needs monitoring
            priority = max(0, priority - 1)
        
        return JobPriority(priority)
    
    def _is_due_for_collection(
        self,
        job,
        settings: Dict[str, Any],
        now: datetime
    ) -> bool:
        """Check if job is due for collection based on its interval."""
        if job.last_collected is None:
            return True
        
        interval_minutes = settings.get(
            'collection_interval_minutes',
            self.config.collection_interval_minutes
        )
        
        due_at = job.last_collected + timedelta(minutes=interval_minutes)
        return now >= due_at
    
    def _estimate_pending_builds(self, job) -> int:
        """Estimate number of pending builds for a job."""
        # This could be enhanced to query the CI platform
        # For now, return a placeholder
        return 0
    
    def _get_recent_failure_rate(self, job, days: int = 7) -> float:
        """Get recent build failure rate for a job."""
        from ci_harvester.db.models import Build
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        builds = self.session.query(Build).filter(
            Build.job_id == job.id,
            Build.created_at >= cutoff,
            Build.result.in_(['success', 'failure', 'unstable'])
        ).all()
        
        if not builds:
            return 0.0
        
        failures = sum(1 for b in builds if b.result in ['failure', 'unstable'])
        return failures / len(builds)
    
    def mark_collected(self, job_id: UUID) -> None:
        """Mark a job as collected."""
        from ci_harvester.db.models import Job
        
        job = self.session.query(Job).filter(Job.id == job_id).first()
        if job:
            job.last_collected = datetime.now(timezone.utc)
            self.session.commit()
            
            logger.info(
                "job_marked_collected",
                job_id=str(job_id),
                job_name=job.name
            )
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get current collection statistics."""
        from ci_harvester.db.models import Job, Build, Product
        
        now = datetime.now(timezone.utc)
        
        # Count jobs by staleness
        stale_30min = self.session.query(Job).filter(
            Job.is_active == True,
            Job.last_collected < now - timedelta(minutes=30)
        ).count()
        
        stale_1hr = self.session.query(Job).filter(
            Job.is_active == True,
            Job.last_collected < now - timedelta(hours=1)
        ).count()
        
        never_collected = self.session.query(Job).filter(
            Job.is_active == True,
            Job.last_collected == None
        ).count()
        
        # Recent builds
        recent_builds = self.session.query(Build).filter(
            Build.created_at >= now - timedelta(hours=1)
        ).count()
        
        return {
            'active_jobs': self.session.query(Job).filter(Job.is_active == True).count(),
            'stale_jobs_30min': stale_30min,
            'stale_jobs_1hr': stale_1hr,
            'never_collected': never_collected,
            'builds_last_hour': recent_builds,
            'timestamp': now.isoformat(),
        }
