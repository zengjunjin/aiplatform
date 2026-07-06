import asyncio
from app.database import engine, async_session
from app.db import Base, User, KnowledgeBase, Document, DocumentChunk, ChatSession, ChatMessage
from app.core.security import hash_password
from sqlalchemy import select
from loguru import logger


async def init():
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tables created")

    # Create default admin user
    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        if not result.scalar_one_or_none():
            admin = User(
                username="admin",
                email="admin@local.dev",
                password_hash=hash_password("admin123"),
                role="admin",
            )
            db.add(admin)
            await db.commit()
            logger.info("Default admin user created (admin / admin123)")
        else:
            logger.info("Admin user already exists")

    await engine.dispose()
    logger.info("Done")


if __name__ == "__main__":
    asyncio.run(init())