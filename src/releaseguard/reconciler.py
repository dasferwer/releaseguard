import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from releaseguard.config import get_settings
from releaseguard.db import session_factory
from releaseguard.domain import ReleaseStatus
from releaseguard.models import Environment, Release, utcnow
from releaseguard.service import add_event, transition

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


async def reconcile_batch() -> int:
    deadline = utcnow() - timedelta(seconds=settings.canary_timeout_seconds)
    async with session_factory() as session, session.begin():
        releases = list(
            (
                await session.scalars(
                    select(Release)
                    .where(
                        Release.status == ReleaseStatus.canary,
                        Release.canary_started_at < deadline,
                    )
                    .limit(25)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for release in releases:
            environment = await session.get(Environment, release.environment_id)
            transition(
                session,
                release,
                ReleaseStatus.rolled_back,
                actor="reconciler",
                reason="canary observation timeout",
            )
            release.traffic_percent = 0
            if environment is not None:
                environment.current_release_id = release.previous_release_id
                environment.active_release_id = None
            add_event(session, release, "canary.timeout", "reconciler")
        return len(releases)


async def run() -> None:
    logger.info("release reconciler started")
    while True:
        try:
            count = await reconcile_batch()
            if count:
                logger.warning("rolled back %s timed out canaries", count)
        except Exception:
            logger.exception("reconciliation failed")
        await asyncio.sleep(settings.reconcile_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run())
