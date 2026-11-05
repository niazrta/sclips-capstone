from sqlalchemy import (
    Column, BigInteger, String, Boolean, Integer,
    ForeignKey, DateTime, Enum, Text, Numeric, func, UniqueConstraint
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
    sinta_publisher_id = Column(BigInteger, nullable=True)
    type = Column(String, nullable=True)             # diisi ML: HEI/GOV/SOC/COM
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    journals = relationship("Journal", back_populates="publisher")

    publisher_size = Column(String, nullable=True)
    type_confidence = Column(Numeric(6, 3), nullable=True)


class Journal(Base):
    __tablename__ = "journals"

    id = Column(BigInteger, primary_key=True, autoincrement=False)
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
        # Data tambahan dari listing SINTA
    website = Column(Text, nullable=True)
    editor_url = Column(Text, nullable=True)
    google_scholar_url = Column(Text, nullable=True)
    garuda_id = Column(BigInteger, nullable=True)
    cover_url = Column(Text, nullable=True)
    rank_badge = Column(String, nullable=True)
    scopus_indexed = Column(Boolean, nullable=True)
    garuda_indexed = Column(Boolean, nullable=True)
    impact = Column(Numeric(10, 2), nullable=True)
    h5_index = Column(Integer, nullable=True)
    citations_5yr = Column(Integer, nullable=True)
    citations = Column(Integer, nullable=True)
    metrics_updated_at = Column(DateTime(timezone=True), nullable=True)

    publisher = relationship("Publisher", back_populates="journals")
    rank_histories = relationship("JournalRankHistory", back_populates="journal")
    
    predicted_subject_sinta = Column(String, nullable=True)
    predicted_subject_sinta_multilabel = Column(String, nullable=True)
    predicted_subject_scopus = Column(String, nullable=True)
    predicted_subject_scopus_27 = Column(String, nullable=True)
    scopus_confidence = Column(Numeric(6, 3), nullable=True)
    predictions_updated_at = Column(DateTime(timezone=True), nullable=True)


class JournalRankHistory(Base):
    __tablename__ = "journal_rank_histories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    journal_id = Column(BigInteger, ForeignKey("journals.id"), nullable=False)
    sinta_rank = Column(String, nullable=False)       # S1-S6
    accreditation_year = Column(Integer, nullable=False)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    journal = relationship("Journal", back_populates="rank_histories")
    __table_args__ = (UniqueConstraint("journal_id", "accreditation_year", name="uq_journal_year"),)


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