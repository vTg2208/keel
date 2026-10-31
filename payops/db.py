import argparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from payops.config import settings
from payops.models import Base


def make_sessions(url=None):
    engine = create_engine(url or settings().database_url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


def migrate():
    # Initial schema is additive. Existing tables are never dropped by deployments.
    engine = create_engine(settings().database_url)
    Base.metadata.create_all(engine)
    engine.dispose()


if __name__ == "__main__":
    argparse.ArgumentParser(description="Initialize the PayOps v1 schema").parse_args()
    migrate()
