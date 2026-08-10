"""启动引导：初始超级管理员 + RBAC 种子。"""

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.password import PasswordHistory
from app.models.user import User
from app.services import rbac_service

logger = get_logger(__name__)


async def ensure_initial_admin() -> None:
    """首次启动且无任何用户时，自动创建初始超级管理员。"""
    if not settings.AUTO_CREATE_ADMIN:
        return
    try:
        async with AsyncSessionLocal() as db:
            count = (
                await db.execute(select(func.count()).select_from(User))
            ).scalar_one()
            if count > 0:
                return
            admin = User(
                username=settings.ADMIN_USERNAME,
                hashed_password=hash_password(settings.ADMIN_PASSWORD),
                is_active=True,
                is_superuser=True,
                full_name="系统管理员",
            )
            db.add(admin)
            await db.flush()
            db.add(
                PasswordHistory(
                    user_id=admin.id, hashed_password=admin.hashed_password
                )
            )
            await db.commit()
            logger.warning(
                "已自动创建初始超级管理员，请立即修改默认密码",
                username=settings.ADMIN_USERNAME,
            )
    except Exception as exc:
        logger.error("初始管理员创建失败", error=str(exc))


async def ensure_rbac_seed() -> None:
    """幂等初始化系统角色/权限点/矩阵并回填存量用户。"""
    try:
        async with AsyncSessionLocal() as db:
            await rbac_service.ensure_rbac_seed(db)
    except Exception as exc:
        logger.error("RBAC 种子初始化失败", error=str(exc))
