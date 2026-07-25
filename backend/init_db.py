import asyncio
import os
import secrets

from loguru import logger
from sqlalchemy import select

from app.core.security import hash_password
from app.database import async_session, engine
from app.db import Base, User


async def init():
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tables created")

    # Create default admin user
    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        if not result.scalar_one_or_none():
            # 优先从环境变量读取初始管理员密码；未设置则生成强随机密码
            admin_password = os.getenv("INITIAL_ADMIN_PASSWORD") or secrets.token_urlsafe(16)
            admin = User(
                username="admin",
                email="admin@local.dev",
                password_hash=hash_password(admin_password),
                role="admin",
            )
            db.add(admin)
            await db.commit()
            # 仅通过 logger 输出，避免密码泄漏到 stdout
            if os.getenv("INITIAL_ADMIN_PASSWORD"):
                logger.info(
                    "Default admin user created (password from INITIAL_ADMIN_PASSWORD env var)"
                )
            else:
                logger.warning(
                    "Admin created with random password (length=%d), set INITIAL_ADMIN_PASSWORD env to override",
                    len(admin_password),
                )
        else:
            logger.info("Admin user already exists")

    await engine.dispose()
    logger.info("Done")


if __name__ == "__main__":
    asyncio.run(init())
