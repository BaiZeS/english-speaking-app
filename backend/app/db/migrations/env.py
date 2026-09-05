from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db.base import Base
from app.models import db as _db_models  # noqa: F401  (register tables)

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False: alembic 默认会**关停**所有已存在的应用
    # logger (fileConfig 的历史包袱)。同进程跑迁移 (tests/test_migrations_sqlite.py)
    # 或 uvicorn 内嵌 upgrade 时, app.* 的 warning 会被静默吞掉 —— 曾以
    # test_scene_store 日志断言在整链跑后必红的形式暴露。日志配置只增不杀。
    fileConfig(config.config_file_name, disable_existing_loggers=False)
db_url = settings.database_url
if db_url.startswith("sqlite+"):
    db_url = db_url.replace("sqlite+aiosqlite", "sqlite")
elif db_url.startswith("postgresql+asyncpg"):
    db_url = db_url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
