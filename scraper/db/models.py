from sqlalchemy import (
    Column, BigInteger, String, Boolean, Integer,
    ForeignKey, DateTime, Enum, Text, Numeric, Date, Time, func, UniqueConstraint
)
from sqlalchemy.orm import relationship
import enum
from db.session import Base
from sqlalchemy.dialects.postgresql import ARRAY


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

    last_detail_scraped_at = Column(DateTime(timezone=True), nullable=True)

    e_issn_status = Column(String, nullable=True)   # valid | short | invalid | none
    p_issn_status = Column(String, nullable=True)
    sinta_affiliation_id = Column(BigInteger, nullable=True)   # ID dari tautan listing, apa adanya


class JournalRankHistory(Base):
    __tablename__ = "journal_rank_histories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    journal_id = Column(BigInteger, ForeignKey("journals.id"), nullable=False)
    sinta_rank = Column(String, nullable=False)       # S1-S6
    accreditation_year = Column(Integer, nullable=False)
    scraped_at = Column(DateTime(timezone=True), server_default=func.now())

    journal = relationship("Journal", back_populates="rank_histories")

    updated_at = Column(DateTime(timezone=True), nullable=True)
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

class SyncRun(Base):
    __tablename__ = "sync_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scope = Column(String, nullable=False)           # new | update | full
    source = Column(String, nullable=True)           # listing | profile | null = sesuai cakupan
    trigger = Column(String, nullable=False)         # scheduled | manual
    requested_by = Column(String, nullable=True)     # admin atau nama jadwal
    target_id = Column(BigInteger, nullable=True)    # ID jurnal bila hanya satu jurnal
    status = Column(String, nullable=False, default="queued")  # queued|running|success|failed|paused
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    sinta_total = Column(Integer, nullable=True)
    db_total_before = Column(Integer, nullable=True)
    total_processed = Column(Integer, default=0)
    total_inserted = Column(Integer, default=0)
    total_updated = Column(Integer, default=0)
    total_skipped = Column(Integer, default=0)
    total_flagged = Column(Integer, default=0)
    pages_failed = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SyncSchedule(Base):
    __tablename__ = "sync_schedules"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    scope = Column(String, nullable=False)           # new | update | full
    frequency = Column(String, nullable=False)       # daily | weekly | monthly | date | cron
    weekdays = Column(ARRAY(Integer), nullable=True) # 0 = Senin ... 6 = Minggu
    month_day = Column(Integer, nullable=True)
    run_date = Column(Date, nullable=True)
    cron_expr = Column(String, nullable=True)
    run_time = Column(Time, nullable=False)
    timezone = Column(String, nullable=False, default="Asia/Jakarta")
    is_active = Column(Boolean, nullable=False, default=False)
    after_ml_predict = Column(Boolean, nullable=False, default=False)
    after_reclassify_publisher = Column(Boolean, nullable=False, default=False)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SyncChange(Base):
    __tablename__ = "sync_changes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(BigInteger, ForeignKey("sync_runs.id"), nullable=False)
    journal_id = Column(BigInteger, ForeignKey("journals.id"), nullable=False)
    field = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())