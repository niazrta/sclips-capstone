from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from config import config


engine = create_engine(
    config.DATABASE_URL,
    echo=False,
    future=True
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()