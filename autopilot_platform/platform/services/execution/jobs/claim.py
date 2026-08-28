"""任务领取。"""

from .lifecycle import claim_job, claim_job_wait

__all__ = ["claim_job", "claim_job_wait"]
