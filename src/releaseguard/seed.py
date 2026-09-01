import asyncio

from sqlalchemy import select

from releaseguard.db import session_factory
from releaseguard.models import Application, Environment


async def seed() -> None:
    async with session_factory() as session:
        application = await session.scalar(
            select(Application).where(Application.slug == "checkout-api-demo")
        )
        if application is None:
            application = Application(
                name="Checkout API",
                slug="checkout-api-demo",
                required_gates=["tests", "security", "signature"],
            )
            session.add(application)
            await session.flush()

        environment = await session.scalar(
            select(Environment).where(
                Environment.application_id == application.id,
                Environment.name == "production",
            )
        )
        if environment is None:
            environment = Environment(
                application_id=application.id,
                name="production",
                requires_approval=True,
                min_requests=100,
                max_error_rate=0.02,
                max_p95_ms=800,
            )
            session.add(environment)
        await session.commit()
        print(f"application_id={application.id} environment_id={environment.id}")


if __name__ == "__main__":
    asyncio.run(seed())
