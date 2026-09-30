from sqlalchemy import (
    Column, BigInteger, String, Boolean, Integer,
    ForeignKey, DateTime, Enum, Text, func
)
from sqlalchemy.orm import relationship
import enum
from db.session import Base


class JournalStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    unverified = "unverified"


class ScrapingStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class Publisher(Base):
    __tablename__ = "publishers"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)          # hasil normalisasi
    raw_name = Column(String, nullable=True)        # nama asli dari SINTA
    type = Column(String, nullable=True)             # diisi ML: HEI/GOV/SOC/COM
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    journals = relationship("Journal", back_populates="publisher")


class Journal(Base):
    __tablename__ = "journals"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    publisher_id = Column(BigInteger, ForeignKey("publishers.id"), nullable=True)
    name = Column(String, nullable=False)
    e_issn = Column(String, nullable=True)
    p_issn = Column(String, nullable=True)
    sinta_url = Column(String, nullable=True)
    current_rank = Column(String, nullable=True)     # S1-S6
    subject = Column(String, nullable=True)            # diisi ML setelah klasifikasi
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(Enum(JournalStatus), default=JournalStatus.unverified, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    publisher = relationship("Publisher", back_populates="journals")
    rank_histories = relationship("JournalRankHistory", back_populates="journal")


class JournalRankHistory(Base):
    __tablename__ = "journal_rank_histories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    journal_id = Column(BigInteger, ForeignKey("journals.id"), nullable=False)
    sinta_rank = Column(String, nullable=False)       # S1-S6
    accreditation_year = Column(Integer, nullable=False)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    journal = relationship("Journal", back_populates="rank_histories")


class ScrapingLog(Base):
    __tablename__ = "scraping_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
    total_scraped = Column(Integer, default=0)
    total_inserted = Column(Integer, default=0)
    total_updated = Column(Integer, default=0)
    total_skipped = Column(Integer, default=0)
    total_flagged = Column(Integer, default=0)
    status = Column(Enum(ScrapingStatus), default=ScrapingStatus.running, nullable=False)
    error_message = Column(Text, nullable=True)