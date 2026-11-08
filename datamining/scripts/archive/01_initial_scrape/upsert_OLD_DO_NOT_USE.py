from datetime import datetime
from sqlalchemy.orm import Session
from db.models import Publisher, Journal, JournalStatus

def upsert_publisher(db: Session, name: str, raw_name: str) -> Publisher:
    publisher = db.query(Publisher).filter(Publisher.name == name).first()
    if publisher:
        if publisher.raw_name != raw_name:
            publisher.raw_name = raw_name
        publisher.is_active = True
        return publisher
    publisher = Publisher(name=name, raw_name=raw_name, is_active=True)
    db.add(publisher)
    db.flush()
    return publisher

def upsert_journal(db: Session, data: dict) -> tuple[Journal, str]:
    """
    data harus punya: name, e_issn, p_issn, sinta_url, current_rank, subject, publisher_id
    return: (journal_object, action) dengan action salah satu dari
    'inserted' | 'updated' | 'skipped'
    """
    journal = db.query(Journal).filter(
        (Journal.e_issn == data.get("e_issn")) | (Journal.sinta_url == data.get("sinta_url"))
    ).first()

    now = datetime.utcnow()

    if journal is None:
        journal = Journal(
            name=data["name"],
            e_issn=data.get("e_issn"),
            p_issn=data.get("p_issn"),
            sinta_url=data.get("sinta_url"),
            current_rank=data.get("current_rank"),
            subject=data.get("subject"),
            publisher_id=data.get("publisher_id"),
            is_active=True,
            status=JournalStatus.active,
            last_seen_at=now,
        )
        db.add(journal)
        db.flush()
        return journal, "inserted"

    changed = (
        journal.name != data["name"]
        or journal.current_rank != data.get("current_rank")
        or journal.p_issn != data.get("p_issn")
        or journal.subject != data.get("subject")
        or journal.publisher_id != data.get("publisher_id")
    )

    journal.last_seen_at = now
    journal.is_active = True
    journal.status = JournalStatus.active

    if changed:
        journal.name = data["name"]
        journal.current_rank = data.get("current_rank")
        journal.p_issn = data.get("p_issn")
        journal.subject = data.get("subject")
        journal.publisher_id = data.get("publisher_id")
        return journal, "updated"

    return journal, "skipped"

def flag_missing_journals(db: Session, found_sinta_urls: list[str]) -> int:
    """Jurnal di DB yang TIDAK ada di hasil scraping kali ini -> flag inactive."""
    journals_to_flag = db.query(Journal).filter(
        Journal.is_active == True,
        ~Journal.sinta_url.in_(found_sinta_urls)
    ).all()
    for j in journals_to_flag:
        j.is_active = False
        j.status = JournalStatus.inactive
    return len(journals_to_flag)

def backfill_subject(db: Session, sinta_url: str, subject: str | None) -> bool:
    if not subject:
        return False
    journal = db.query(Journal).filter(Journal.sinta_url == sinta_url).first()
    if journal and not journal.subject:
        journal.subject = subject
        return True
    return False