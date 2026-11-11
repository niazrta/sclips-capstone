import asyncio
import hashlib
import json
import logging
import math
import os
import pickle
import re
import sqlite3
import threading
import uuid
import warnings
import io
import zlib
from collections.abc import MutableMapping
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

import numpy as np
import sklearn
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sklearn.preprocessing import Normalizer

logger = logging.getLogger("sclips.ml_service")

# ==============================================================================
# KONSTANTA DOMAIN, PEMETAAN HIERARKI SCOPUS/SINTA, & CHECKSUM MODEL
# ==============================================================================
MODEL_FILENAME_DEFAULT: str = "sclips_models_v2.7.pkl"
# Diisi otomatis oleh skrip pelatihan v2.7 (train_v27.py) setelah .pkl selesai dibuat.
DEFAULT_MODEL_SHA256: str = "5e9841f96ba473a6faefe1d7a2b853e6c3393b3ccc92960c2f1a23c79886fd37"
KNOWN_VALID_MODEL_SHA256S: Set[str] = {
    DEFAULT_MODEL_SHA256,
}

PUBLISHER_TYPES: List[str] = ["COM", "GOV", "HEI", "SOC"]
SCOPUS_4_CLUSTERS: List[str] = [
    "Health Sciences",
    "Life Sciences",
    "Physical Sciences",
    "Social Sciences",
]
SINTA_10_SUBJECTS: List[str] = [
    "Agriculture",
    "Art",
    "Economy",
    "Education",
    "Engineering",
    "Health",
    "Humanities",
    "Religion",
    "Science",
    "Social",
]
SINTA_TO_SCOPUS_MAP: Dict[str, str] = {
    "Health": "Health Sciences",
    "Agriculture": "Life Sciences",
    "Engineering": "Physical Sciences",
    "Science": "Physical Sciences",
    "Education": "Social Sciences",
    "Economy": "Social Sciences",
    "Social": "Social Sciences",
    "Religion": "Social Sciences",
    "Humanities": "Social Sciences",
    "Art": "Social Sciences",
}

SCOPUS_27_TO_SUPERGROUP: Dict[str, str] = {
    "Computer Science": "Physical Sciences",
    "Engineering": "Physical Sciences",
    "Mathematics": "Physical Sciences",
    "Physics and Astronomy": "Physical Sciences",
    "Chemistry": "Physical Sciences",
    "Chemical Engineering": "Physical Sciences",
    "Materials Science": "Physical Sciences",
    "Energy": "Physical Sciences",
    "Environmental Science": "Physical Sciences",
    "Earth and Planetary Sciences": "Physical Sciences",
    "Medicine": "Health Sciences",
    "Nursing": "Health Sciences",
    "Dentistry": "Health Sciences",
    "Veterinary": "Health Sciences",
    "Health Professions": "Health Sciences",
    "Agricultural and Biological Sciences": "Life Sciences",
    "Pharmacology, Toxicology and Pharmaceutics": "Life Sciences",
    "Biochemistry, Genetics and Molecular Biology": "Life Sciences",
    "Immunology and Microbiology": "Life Sciences",
    "Neuroscience": "Life Sciences",
    "Social Sciences": "Social Sciences",
    "Business, Management and Accounting": "Social Sciences",
    "Economics, Econometrics and Finance": "Social Sciences",
    "Arts and Humanities": "Social Sciences",
    "Psychology": "Social Sciences",
    "Decision Sciences": "Social Sciences",
    "Multidisciplinary": "Multidisciplinary",
}

SCOPUS_27_TO_INDONESIAN: Dict[str, str] = {
    "Computer Science": "Ilmu Komputer",
    "Engineering": "Teknik",
    "Mathematics": "Matematika",
    "Physics and Astronomy": "Fisika & Astronomi",
    "Chemistry": "Kimia",
    "Chemical Engineering": "Teknik Kimia",
    "Materials Science": "Ilmu Material",
    "Energy": "Energi",
    "Environmental Science": "Ilmu Lingkungan",
    "Earth and Planetary Sciences": "Ilmu Bumi & Planet",
    "Medicine": "Kedokteran",
    "Nursing": "Keperawatan",
    "Dentistry": "Kedokteran Gigi",
    "Veterinary": "Kedokteran Hewan",
    "Health Professions": "Profesi Kesehatan",
    "Agricultural and Biological Sciences": "Ilmu Pertanian & Biologi",
    "Pharmacology, Toxicology and Pharmaceutics": "Farmakologi, Toksikologi & Farmasi",
    "Biochemistry, Genetics and Molecular Biology": "Biokimia, Genetika & Biologi Molekuler",
    "Immunology and Microbiology": "Imunologi & Mikrobiologi",
    "Neuroscience": "Neurosains",
    "Social Sciences": "Ilmu Sosial",
    "Business, Management and Accounting": "Bisnis, Manajemen & Akuntansi",
    "Economics, Econometrics and Finance": "Ekonomi, Ekonometrika & Keuangan",
    "Arts and Humanities": "Seni & Humaniora",
    "Psychology": "Psikologi",
    "Decision Sciences": "Ilmu Pengambilan Keputusan",
    "Multidisciplinary": "Multidisiplin",
}

# Bidang Scopus-27 yang sah untuk tiap bidang SINTA-10 (elemen pertama = default).
# Dipakai DUA tempat agar tidak ada train-serve skew:
#   (1) notebook training -> membentuk label silver Scopus-27 (hanya boleh memilih bidang yang sah),
#   (2) service -> cek konsistensi hierarki SINTA-10 vs Scopus-4 vs Scopus-27.
# Contoh: jurnal Farmasi (SINTA Health) sah berlabel "Pharmacology..." walau supergroup Scopus-nya
# Life Sciences, sehingga tidak boleh otomatis dianggap tidak konsisten.
SCOPUS27_ALLOWED_BY_SINTA: Dict[str, List[str]] = {
    "Health": [
        "Medicine", "Nursing", "Health Professions", "Pharmacology, Toxicology and Pharmaceutics",
        "Dentistry", "Veterinary", "Immunology and Microbiology", "Neuroscience", "Psychology",
        "Biochemistry, Genetics and Molecular Biology",
    ],
    "Agriculture": [
        "Agricultural and Biological Sciences", "Veterinary", "Environmental Science",
        "Biochemistry, Genetics and Molecular Biology", "Immunology and Microbiology",
        "Economics, Econometrics and Finance", "Engineering",
    ],
    "Engineering": [
        "Engineering", "Computer Science", "Chemical Engineering", "Materials Science", "Energy",
        "Environmental Science", "Earth and Planetary Sciences", "Mathematics", "Decision Sciences",
    ],
    "Science": [
        "Multidisciplinary", "Mathematics", "Physics and Astronomy", "Chemistry", "Computer Science",
        "Agricultural and Biological Sciences", "Biochemistry, Genetics and Molecular Biology",
        "Environmental Science", "Earth and Planetary Sciences", "Materials Science",
        "Immunology and Microbiology", "Pharmacology, Toxicology and Pharmaceutics",
    ],
    "Education": ["Social Sciences", "Psychology"],
    "Economy": [
        "Economics, Econometrics and Finance", "Business, Management and Accounting", "Decision Sciences",
    ],
    "Social": ["Social Sciences", "Psychology", "Decision Sciences"],
    "Religion": ["Arts and Humanities", "Social Sciences"],
    "Humanities": ["Arts and Humanities", "Social Sciences", "Psychology"],
    "Art": ["Arts and Humanities", "Social Sciences"],
}

PUBLISHER_SOURCE_OVERRIDE: str = "verified_override"
PUBLISHER_SOURCE_RULE: str = "morphology_rule"
PUBLISHER_SOURCE_MODEL: str = "model"
PUBLISHER_SOURCE_OOD: str = "ood"
PUBLISHER_SOURCE_NONE: str = "no_publisher"

MAX_BATCH_SIZE: int = 20000
INTERNAL_CHUNK_SIZE: int = 1000
DEFAULT_SCOPUS4_CONFIDENCE_THRESHOLD: float = 55.0
DEFAULT_SINTA10_CONFIDENCE_THRESHOLD: float = 40.0
DEFAULT_SCOPUS27_CONFIDENCE_THRESHOLD: float = 40.0
DEFAULT_PUBLISHER_CONFIDENCE_THRESHOLD: float = 70.0
DEFAULT_SINTA_MULTILABEL_THRESHOLD_PCT: float = 35.0

# ---------------- v2.7 ----------------
# Ambang keyakinan label yang ditampilkan (subjek & tipe penerbit). Keyakinan subjek v2.7 = peluang label
# yang ditampilkan memang termasuk subjek SINTA jurnal itu (kalibrasi isotonik out-of-fold).
DEFAULT_LABEL_CONFIDENCE_THRESHOLD: float = 70.0
MULTIDISCIPLINARY_LABEL: str = "Multidisciplinary"
MULTIDISCIPLINARY_LABEL_ID: str = "Multidisiplin"
# Jurnal dengan subjek SINTA asli sebanyak >= nilai ini ditampilkan sebagai "Multidisciplinary".
MULTIDISCIPLINARY_MIN_SINTA_SUBJECTS: int = 4
LABEL_LEVEL_SUBJECT: str = "subjek"
LABEL_LEVEL_PAIR: str = "dua_subjek"
LABEL_LEVEL_RUMPUN: str = "rumpun"
PUBLISHER_SOURCE_DEFAULT_INDEPENDENT: str = "aturan_default_independen"
PUBLISHER_SOURCE_PRIOR_NO_NAME: str = "prior_tanpa_nama_penerbit"
PUBLISHER_SOURCE_NO_PUBLISHER: str = "tanpa_penerbit"
# Jurnal tanpa nama penerbit (kosong / "Unknown" / "-") TIDAK diberi tipe & ukuran penerbit (kesepakatan Data Mining).
# Set SCLIPS_ASSIGN_TYPE_WITHOUT_PUBLISHER=1 untuk kembali ke perilaku lama (label mayoritas HEI + Needs Review).
ASSIGN_TYPE_WITHOUT_PUBLISHER: bool = os.getenv("SCLIPS_ASSIGN_TYPE_WITHOUT_PUBLISHER", "0").strip().lower() in {"1", "true", "yes"}
SINTA_TO_INDONESIAN: Dict[str, str] = {
    "Agriculture": "Pertanian", "Art": "Seni", "Economy": "Ekonomi", "Education": "Pendidikan",
    "Engineering": "Teknik", "Health": "Kesehatan", "Humanities": "Humaniora", "Religion": "Agama",
    "Science": "Sains", "Social": "Sosial",
}
SCOPUS_4_TO_INDONESIAN: Dict[str, str] = {
    "Health Sciences": "Ilmu Kesehatan", "Life Sciences": "Ilmu Hayati", "Physical Sciences": "Ilmu Fisik",
    "Social Sciences": "Ilmu Sosial", "Multidisciplinary": "Multidisiplin",
}


def compile_word_boundary_regex(keywords: List[str]) -> re.Pattern:
    escaped = [re.escape(k.strip()) for k in sorted(keywords, key=len, reverse=True) if k.strip()]
    return re.compile(r"(?<![a-zA-Z0-9'])(?:" + "|".join(escaped) + r")(?![a-zA-Z0-9'])", flags=re.IGNORECASE)


VERIFIED_PUBLISHER_OVERRIDES: Dict[str, str] = {
    # 1. Asosiasi / Komunitas Ilmiah (SOC)
    "institute of advanced engineering and science (iaes)": "SOC",
    "institute of advanced engineering and science": "SOC",
    "iaes": "SOC",
    "management research center": "SOC",
    "management research center (mrc)": "SOC",
    "mrc": "SOC",
    "akademi ilmu pengetahuan indonesia": "SOC",
    "aipi": "SOC",
    "lembaga pendidikan ma'arif nu": "SOC",
    "majelis pendidikan pwm diy": "SOC",
    "perkumpulan kimia indonesia": "SOC",
    "himpunan kimia indonesia": "SOC",
    "ikatan akuntan indonesia": "SOC",
    "ikatan apoteker indonesia": "SOC",
    # 2. Unit Kampus / University Press Khusus (HEI)
    "talenta publisher": "HEI",
    "efpress digimedia": "HEI",
    "badan penerbit fhui": "HEI",
    "badan penerbit fkui": "HEI",
    "badan penerbit universitas diponegoro": "HEI",
    "badan penerbit unm": "HEI",
    "iai darussalam": "HEI",
    "institut agama islam darussalam": "HEI",
    "unitri press": "HEI",
    "uinsu press": "HEI",
    "undiksha press": "HEI",
    "pusat penelitian dan pengabdian masyarakat": "HEI",
    "pusat penelitian dan pengabdian kepada masyarakat": "HEI",
    "lembaga penelitian dan pengabdian masyarakat": "HEI",
    "lembaga penelitian dan pengabdian kepada masyarakat": "HEI",
    # 3. Instansi / Balai Riset Pemerintah (GOV)
    "badan informasi geospasial": "GOV",
    "badan pembinaan hukum nasional": "GOV",
    "lembaga penerbangan dan antariksa nasional": "GOV",
    "balai bahasa bali": "GOV",
    "balai bahasa provinsi jawa timur": "GOV",
    "balai bahasa jawa timur": "GOV",
    "pusat penelitian karet": "GOV",
    "pusat penelitian kelapa sawit": "GOV",
    "pusat penelitian kopi dan kakao indonesia": "GOV",
    "pusat penelitian teh dan kina": "GOV",
    "pusat penelitian perkebunan gula indonesia": "GOV",
    "pt riset perkebunan nusantara": "GOV",
    "balai penerapan standar instrumen lingkungan hidup dan kehutanan (bpsilhk) solo dan masyarakat konservasi tanah dan air indonesia (mkti)": "GOV",
    # 4. Penerbit Swasta / Komersial (COM)
    "puslitbang sinergis asa professional": "COM",
    "lembaga pengembangan kinerja dosen": "COM",
    "lpkd": "COM",
    "sean institute": "COM",
    "yayasan sean institute": "COM",
    "institute of computer science": "COM",
    "institute of computer science (iocs)": "COM",
    "indonesian institute for counseling, education and therapy": "COM",
    "indonesian institute for counseling, education and therapy (iicet)": "COM",
    "ridwan institute": "COM",
    "cv. ridwan institute": "COM",
    "cattleya darmaya fortuna": "COM",
    "global eksekutif teknologi": "COM",
    "pt. global eksekutif teknologi": "COM",
    "intelektual pustaka media utama": "COM",
    "yayasan kita menulis": "COM",
    "yayasan pendidikan cendekia muslim": "COM",
    "green publisher indonesia": "COM",
    "cv. green publisher": "COM",
    "syntax corporation indonesia": "COM",
    "cv. syntax corporation indonesia": "COM",
    # Bukan instansi pemerintah walau mengandung frasa "pusat pengembangan" (pola GOV):
    # situs jurnalp4i.com, alamat redaksi Kel. Leneng, Praya, Lombok Tengah. Bentuk badan hukum belum
    # terkonfirmasi -> diberi COM (default penerbit independen non-kampus). Verifikasi ke AHU bila perlu.
    "pusat pengembangan pendidikan dan penelitian indonesia": "COM",
    "pusat pengembangan pendidikan dan penelitian indonesia (p4i)": "COM",
}

TRUE_CAMPUS_ENTITY_PATTERN = compile_word_boundary_regex([
    "universitas", "university", "universiti",
    "institut", "institute of technology", "islamic institute", "state islamic",
    "institute of the arts", "perbanas institute", "kalbis institute", "lspr", "stiami", "bio scientia",
    "politeknik", "polytechnic", "poltekkes", "poltek", "polbangtan", "politani",
    "poltekip", "poltekim", "poltekbang", "poltekpel", "poltekpar", "polteksos",
    "sekolah tinggi", "sekolah vokasi", "program vokasi", "fakultas vokasi",
    "akademi", "akper", "akbid", "akfar", "akafarma", "akanalis", "akfis", "akzi", "akpar", "akpelni", "akmil", "akpol", "amik", "amk", "asm", "akakom", "akprind", "atmi", "akamigas",
    "uin", "iain", "stain", "iai", "iaid", "iaim", "iainu", "iais", "iaib", "iait", "iaifa", "iailm", "iaiq", "iakn", "iahn",
    "stikes", "stkip", "stmik", "stie", "stis", "stai", "stais", "staida", "staim", "stainu", "staip", "staia", "stiba", "stiq", "stiu", "stfi",
    "stth", "stti", "stta", "sttn", "sttw", "sttkd", "sttm", "sttr", "stts", "stba", "stih", "stia", "stif", "stifar", "stifi", "stip", "stiper", "stisip", "stisipol",
    "stit", "stisnu", "stitnu", "stitm", "stid", "stida", "stidr", "stidki", "stf", "stfk", "stpkat", "stakat", "stpmd", "stpm", "stim", "stimik", "stimart", "stipan", "stipap", "stikp", "stikep", "stikb", "stikma", "stikv", "starki", "stkq", "stkp", "staiyo", "staimas", "staima", "staiq", "stsi", "stsrd", "stmi", "stpp", "stpt", "sttd", "stft", "stak", "stakn", "stakpn", "stahn", "stabn", "sthd", "stab", "stik", "ptik", "stikom", "stikubank", "stiks", "stipram", "stiepar", "stiep", "stiem", "stien", "sties", "stt",
    "ikip", "ipdn", "stpdn", "pkn stan", "stsn", "stmkg", "stpn", "stin", "sthm", "stks", "sesko",
    "isbi", "ikj", "isi yogyakarta", "isi surakarta", "isi denpasar", "isi padangpanjang", "itera", "itk", "it del", "itsk", "itkes",
    "fakultas", "faculty", "program studi", "study program", "prodi", "jurusan",
    "pascasarjana", "postgraduate", "graduate school", "graduate program", "sekolah pascasarjana",
    "lppm", "lp2m", "lp3m", "lpm", "lp3", "lpp", "p3m", "pppm", "uppm", "lemlit", "puslitabmas", "penelitian dan pengabdian", "pengabdian masyarakat", "pengabdian kepada masyarakat", "research and community service", "community service",
    "fhui", "fkui", "febui", "ftui", "fisipui", "fibui", "fmipaui", "fkmui", "fkgui", "ffui", "fasilkom",
    "undip", "ugm", "ui", "itb", "ipb", "its", "unair", "unpad", "ub", "unhas", "uns", "uny", "unnes",
    "um", "upi", "unesa", "usu", "unand", "unsri", "unila", "unri", "unsyiah", "usk", "unram", "undana",
    "unpatti", "uncen", "untan", "unlam", "ulm", "unmul", "untad", "unhalu", "uho", "ung", "unsrat",
    "unima", "undiksha", "unib", "unja", "unsika", "untirta", "unsoed", "unej", "upn", "umm", "ums",
    "umy", "uad", "uii", "unisba", "unpas", "unikom", "binus", "telkom university", "ittelkom", "ittp", "gunadarma",
    "trisakti", "tarumanagara", "untar", "atmajaya", "petra", "ubaya", "widya mandala", "sanata dharma",
    "parahyangan", "unpar", "maranatha", "ukdw", "uksw", "ukrida", "uki", "uhamka", "umsu", "ump", "umsida", "umj",
    "unissula", "unisma", "unimus", "unisnu", "unwahas", "ugj", "unsil", "unjani", "widyatama", "itenas", "itn", "itats",
    "unusa", "unitomo", "untag", "uwks", "uty", "umby", "unisa", "upgris", "udinus", "unisbank", "usm", "unika",
    "unitri", "uinsu", "uinsgd", "uinsuka", "uinjkt", "uinarraniry", "uinalauddin", "uinradenfatah", "uinwalisongo", "uinantasari", "uinib", "uinmataram", "uinrms", "uinsatu", "uinfas", "uindatokarama", "uinsyahada", "uinbukittinggi", "uinpekalongan", "uinsalatiga", "uinkhas", "unirow", "unmas", "undiknas", "unhi", "unizar", "unidayan", "unibos", "umi", "uit", "unimed", "unpam", "unp", "uir", "unm", "unj", "untidar", "uniska", "uniku", "unibba", "unigal", "unipa", "unmus", "unkhair", "unsulbar", "unimor",
    "unismuh", "unipma", "unidha", "unbari", "unhaz", "unikal", "unikama", "uniks", "unilak", "unimar", "unimas", "uninus", "unipdu", "unira", "univrab", "unwiku", "unwir", "unwim", "unwira", "unuja", "unugiri",
    "polines", "polban", "polinema", "pens", "ppns", "polije", "polibatam", "polmed", "polsri", "pnp", "pnj", "pnb", "pnl", "politala", "polindra", "polman", "polimdo", "polnep", "polbeng",
    "talenta publisher", "badan penerbit fhui", "badan penerbit fkui", "badan penerbit universitas", "badan penerbit undip", "badan penerbit unm", "badan penerbit isi", "badan penerbitan"
])

UNIV_PRESS_REGEX = re.compile(
    r"(?<![a-zA-Z0-9'])(?:universitas|university|institut|politeknik|poltekkes|stikes|stkip|stmik|stie|stai|stit|uin|iain|stain|ikip|"
    r"un(?!it\b|ion\b|iversal\b|ique\b|ited\b|tuk\b)[a-z0-9]{2,10}|"
    r"uin[a-z0-9]{0,10}|iain[a-z0-9]{0,10}|stain[a-z0-9]{0,10}|"
    r"st(?!andar\b|ar\b|udio\b|rategi\b|asiun\b)[a-z0-9]{1,8}|"
    r"pol(?!ri\b|itik\b|isi\b|aris\b)[a-z0-9]{2,9}|"
    r"ugm|ui|itb|ipb|its|ub|um|upi|usu|usk|uho|ung|upn|uir|umm|ums|umy|uad|uii|binus|ukdw|uksw|usd|uhamka|umsu|ump|umsida|umj|uty|umby|usm|uisu|uma|upy|ust|umi|uit|"
    r"itera|itk|isi|isbi|ikj|pens|pnp|pnj|pnb|pnl)\s+(?:university\s+)?(?:press|publisher|publishing)(?![a-zA-Z0-9'])",
    flags=re.IGNORECASE
)

STARTS_WITH_PT_CV = re.compile(
    r"^\s*(?:pt\.?\s+|cv\.?\s+|ud\.?\s+|firma\s+|perseroan\s+)(?!riset\s+perkebunan\s+nusantara)",
    flags=re.IGNORECASE
)

STARTS_WITH_SOC_PREFIX = re.compile(
    r"^\s*(?:"
    r"asosiasi|association|perhimpunan|perkumpulan|himpunan|persatuan|konsorsium|consortium|"
    r"forum|aliansi|alliance|federasi|federation|kolegium|collegium|jejaring|jaringan|komunitas|"
    r"masyarakat|society|union|badan\s+kerja\s*sama|bks[\s\-]ptn|bkstm|"
    r"ikatan\s+(?!agama\s+islam)|"
    r"majelis\s+(?!permusyawaratan\s+rakyat)|"
    r"pengurus\s+(?:pusat|besar|wilayah|daerah|cabang)|"
    r"pimpinan\s+(?:pusat|wilayah|daerah|cabang)|"
    r"dpp\b|dpw\b|dpd\s+(?!ri\b|republik\s+indonesia)|"
    r"lembaga\s+pendidikan\s+ma\'?arif|relawan\s+jurnal|rji\b|"
    r"institute\s+of\s+advanced\s+engineering|iaes\b|ieee\b|acm\b|"
    r"aptisi\b|aptikom\b|aptik\b|adri\b|adrii\b|adpi\b|aipki\b|aipni\b|aipkind\b|aipgi\b|aptfi\b|apdfi\b|afeb\b|forkomsii\b|fppti\b|appti\b|apjiki\b|"
    r"icmi\b|aipi\b|pgri\b|igi\b|idi\b|ppni\b|ibi\b|pdgi\b|himpsi\b|perdossi\b|perki\b|papdi\b|idai\b|pogi\b|perhati\b|persi\b|iakmi\b|persagi\b|pafi\b|patelki\b|pormiki\b|"
    r"hki\b|pbi\b|pii\b|isei\b|hagi\b|iagi\b|perhepi\b|perhorti\b|peragi\b|perhimpi\b|hiti\b|hatti\b|ispi\b|hisfarsi\b|isfi\b"
    r")",
    flags=re.IGNORECASE
)

SOC_EXPLICIT_PATTERN = re.compile(
    r"(?<![a-zA-Z0-9'])(?:"
    r"institute of advanced engineering and science|iaes|aptisi|aptikom|aptik|adpi|adrii|relawan jurnal indonesia|rji|"
    r"akademi ilmu pengetahuan indonesia|aipi|badan kerja\s*sama perguruan tinggi|bks[\s\-]ptn|bkstm|"
    r"ikatan akuntan indonesia|ikatan apoteker indonesia|"
    r"(?:asosiasi|perhimpunan|ikatan|perkumpulan|himpunan|persatuan|konsorsium|forum|aliansi|federasi|kolegium|jejaring|jaringan|komunitas)\s+"
    r"(?:program studi|prodi|jurusan|departemen|fakultas|dekan|dosen|guru besar|profesor|rektor|pimpinan|alumni|perguruan tinggi|universitas|institut|politeknik|institusi pendidikan|pendidikan tinggi|pengelola|jurnal|profesi|keilmuan|ahli|sarjana|ilmuwan|peneliti|pendidik)"
    r")(?![a-zA-Z0-9'])",
    flags=re.IGNORECASE,
)

STARTS_WITH_HEI_OR_GOV = re.compile(
    r"^\s*(?:universitas|university|universiti|institut\b(?!\s+of advanced engineering)|politeknik|poltekkes|akademi\b(?!\s+ilmu pengetahuan indonesia)|sekolah tinggi|"
    r"uin|iain|stain|iai\b(?!\s*[\(\-]?\s*ikatan)|iakn|iahn|stikes|stkip|stmik|stie|stis|stai|stt\b|ikip|fakultas|faculty|program studi|study program|prodi|jurusan|departemen|department|"
    r"lppm|lp2m|lp3m|p3m|uppm|pascasarjana|postgraduate|kementerian|ministry|badan\b(?!\s+kerja\s*sama)|balai|loka|kantor|puslitbang|pusat penelitian|pusat riset|dinas|brin|lipi)",
    flags=re.IGNORECASE,
)

GOV_BADAN_SAFE_RE = re.compile(
    r"(?<![a-zA-Z0-9'])badan\s+(?!penerbit|publikasi|pengelola\s+jurnal|kerja\s*sama|eksekutif\s+mahasiswa|semi\s+otonom|wakaf\s+uii|usaha|hukum|musyawarah|pengurus|pimpinan)",
    flags=re.IGNORECASE
)

GOV_PATTERN = compile_word_boundary_regex([
    "kementerian", "kemenkes", "kemendikbud", "kemendikbudristek", "kemdiktisaintek", "kemenristekdikti",
    "kemenag", "kemenkeu", "kemenkumham", "kemenperin", "kemendag", "kementan", "kemenhub",
    "kemenkominfo", "kominfo", "komdigi", "kemenparekraf", "kemenpora", "kemenaker", "kemenkop", "kemenpppa",
    "kemenpan", "kemensos", "kemenpupr", "klhk", "kkp", "esdm", "atrbpn", "kemendagri", "kemhan", "kemenlu", "kemendes", "kemenbumn",
    "ministry", "national research and innovation agency", "indonesian institute of sciences",
    "departemen kesehatan ri", "departemen pekerjaan umum", "departemen pertanian", "departemen keuangan",
    "departemen agama", "departemen pendidikan nasional", "departemen dalam negeri", "departemen kehutanan",
    "departemen perindustrian", "departemen perhubungan", "departemen sosial", "departemen energi", "departemen kelautan",
    "lldikti", "lembaga layanan pendidikan tinggi", "kopertis", "koordinator perguruan tinggi swasta",
    "bphn", "brin", "lipi", "lembaga ilmu pengetahuan", "bkpk", "bskdn", "bskap", "bpip", "bpjph", "bpjs", "baznas", "bwi", "bpkh", "bkpm", "bp2mi",
    "lembaga penerbangan dan antariksa nasional", "lembaga administrasi negara", "lembaga ketahanan nasional", "lemhannas", "wantannas",
    "lembaga kebijakan pengadaan", "lembaga penjamin simpanan", "lembaga perlindungan saksi", "lembaga sensor film", "lembaga penyiaran publik", "lembaga sandi negara", "lembaga biologi molekuler eijkman",
    "bpsdm", "bpsdmp", "bpsdmd", "bkpsdm", "ppsdm", "pusdiklat", "pusat pendidikan dan pelatihan", "pusat pengembangan sumber daya manusia",
    "balitbang", "balitbangda", "balitbangnovda", "puslitbang", "pusat penelitian dan pengembangan", "pusat penelitian", "puslit", "pusat riset",
    "pusat pengkajian", "pusat pengembangan", "pusat data", "pusdatin", "pusat kurikulum", "pusat asesmen", "pusat pembinaan", "pusat kebijakan",
    "lemigas", "tekmira", "pusjatan", "pusair", "puskim", "puslitbangnak", "puslitbangtan", "puslitbanghorti", "puslitbangbun", "puslitkoka", "ppks", "p3gi",
    "balai", "loka", "stasiun penelitian", "bpsilhk", "bsilhk", "bpsi", "bpsip", "bsip", "bptp", "bp2lhk", "bpcb", "bpnb", "baristand", "bapelkes",
    "bpk", "bpkp", "bdk", "lpmp", "bgp", "bbgp", "bbpmp", "bpmp", "bbppmpv", "pppptk", "p4tk",
    "kantor bahasa", "kantor wilayah", "kanwil", "kantor kementerian", "kantor kesehatan pelabuhan", "kantor kesyahbandaran", "kantor otoritas",
    "badan pusat statistik", "statistics indonesia", "bps", "badan informasi geospasial", "geospatial information agency", "big",
    "badan siber", "bssn", "badan nasional", "basarnas", "bnpb", "bnpt", "bnn", "bkkbn", "bmkg", "bapeten", "bakamla",
    "mahkamah", "supreme court", "constitutional court", "pengadilan tinggi", "pengadilan negeri", "pengadilan agama", "ptun",
    "komisi", "kpu", "bawaslu", "kpk", "kpud", "ombudsman", "komnas", "kppu", "kpai", "kpi", "kasn",
    "dinas", "dislitbang", "pemerintah", "pemprov", "pemkab", "pemkot",
    "bappeda", "bappedalitbang", "bappelitbangda", "bappelitbang", "bapelitbang", "bapelitbangda", "bapperida", "bappenas", "brida", "bpbd", "bakesbangpol", "bkd",
    "bpom", "batan", "lapan", "bppt", "perpusnas", "perpustakaan nasional", "arsip nasional", "anri", "bsn", "lkpp", "bkn",
    "bank indonesia", "otoritas jasa keuangan", "ojk", "lps", "lpsk", "ppatk", "dpr", "mpr", "dpd ri", "dprd",
    "rumah sakit umum daerah", "rumah sakit umum pusat", "rumah sakit jiwa", "rumah sakit kanker", "rumah sakit jantung", "rumah sakit penyakit infeksi",
    "rumah sakit ortopedi", "rumah sakit paru", "rumah sakit mata", "rumah sakit ketergantungan obat", "rumah sakit pusat", "rumah sakit bhayangkara",
    "rsud", "rsup", "rsupn", "rsjpd", "rskd", "rsj", "rspad", "rspi", "rso", "rsm", "rsko", "rsab", "rst",
    "kejaksaan", "kepolisian", "polri", "tni", "tentara nasional", "sekretariat negara", "sekretariat kabinet",
    "sekretariat jenderal", "setjen", "inspektorat jenderal", "itjen", "direktorat jenderal", "ditjen", "direktorat",
    "museum nasional", "museum negeri", "galeri nasional", "taman budaya", "rri", "tvri"
])

HEI_PATTERN = compile_word_boundary_regex([
    "universitas", "university", "universiti", "institut", "institute of technology", "islamic institute", "state islamic",
    "institute of the arts", "perbanas institute", "kalbis institute", "lspr", "stiami", "bio scientia",
    "politeknik", "polytechnic", "poltekkes", "poltek", "polbangtan", "politani", "poltekip", "poltekim", "poltekbang", "poltekpel", "poltekpar", "polteksos",
    "akademi", "academy", "akper", "akbid", "akfar", "akafarma", "akanalis", "akfis", "akzi", "akpar", "akpelni", "akmil", "akpol", "amik", "amk", "asm", "akakom", "akprind", "atmi", "akamigas",
    "sekolah tinggi", "college", "school of", "graduate school", "sekolah vokasi", "program vokasi", "fakultas vokasi", "vocational school",
    "uin", "iain", "stain", "iai", "iaid", "iaim", "iainu", "iais", "iaib", "iait", "iaifa", "iailm", "iaiq", "iakn", "iahn",
    "stikes", "stkip", "stmik", "stie", "stis", "stai", "stais", "staida", "staim", "stainu", "staip", "staia", "stiba", "stiq", "stiu", "stfi",
    "stth", "stti", "stta", "sttn", "sttw", "sttkd", "sttm", "sttr", "stts", "stba", "stih", "stia", "stif", "stifar", "stifi", "stip", "stiper", "stisip", "stisipol",
    "stit", "stisnu", "stitnu", "stitm", "stid", "stida", "stidr", "stidki", "stf", "stfk", "stpkat", "stakat", "stpmd", "stpm", "stim", "stimik", "stimart", "stipan", "stipap", "stikp", "stikep", "stikb", "stikma", "stikv", "starki", "stkq", "stkp", "staiyo", "staimas", "staima", "staiq", "stsi", "stsrd", "stmi", "stpp", "stpt", "sttd", "stft", "stak", "stakn", "stakpn", "stahn", "stabn", "sthd", "stab", "stik", "ptik", "stikom", "stikubank", "stiks", "stipram", "stiepar", "stiep", "stiem", "stien", "sties", "stt",
    "ikip", "ipdn", "stpdn", "pkn stan", "stsn", "stmkg", "stpn", "stin", "sthm", "stks", "sesko",
    "isbi", "ikj", "isi yogyakarta", "isi surakarta", "isi denpasar", "isi padangpanjang", "itera", "itk", "it del", "itsk", "itkes",
    "fakultas", "faculty", "program studi", "study program", "prodi", "jurusan", "departemen", "department",
    "lppm", "lp2m", "lp3m", "lpm", "lp3", "lpp", "p3m", "pppm", "uppm", "lemlit", "puslitabmas", "penelitian dan pengabdian", "pengabdian masyarakat", "pengabdian kepada masyarakat", "research and community service", "community service", "community service institute",
    "pascasarjana", "postgraduate", "graduate program", "magister", "master program", "doctoral program", "kampus", "rektorat", "dekanat", "rumah jurnal", "upt jurnal", "upt publikasi", "upt penerbitan",
    "fhui", "fkui", "febui", "ftui", "fisipui", "fibui", "fmipaui", "fkmui", "fkgui", "ffui", "fasilkom",
    "feb", "fisip", "fkip", "fmipa", "faperta", "fapet", "fpik", "fkm", "fkg", "fsm", "ftk", "fts", "fti", "ftsp", "ftmd", "fttm", "fitb", "sappk", "sbm", "sith", "stei", "fsrd",
    "undip", "ugm", "ui", "itb", "ipb", "its", "unair", "unpad", "ub", "unhas", "uns", "uny", "unnes",
    "um", "upi", "unesa", "usu", "unand", "unsri", "unila", "unri", "unsyiah", "usk", "unram", "undana",
    "unpatti", "uncen", "untan", "unlam", "ulm", "unmul", "untad", "unhalu", "uho", "ung", "unsrat",
    "unima", "undiksha", "unib", "unja", "unsika", "untirta", "unsoed", "unej", "upn", "umm", "ums",
    "umy", "uad", "uii", "unisba", "unpas", "unikom", "binus", "telkom university", "ittelkom", "ittp", "gunadarma",
    "trisakti", "tarumanagara", "untar", "atmajaya", "petra", "ubaya", "widya mandala", "sanata dharma",
    "parahyangan", "unpar", "maranatha", "ukdw", "uksw", "ukrida", "uki", "uhamka", "umsu", "ump", "umsida", "umj",
    "unissula", "unisma", "unimus", "unisnu", "unwahas", "ugj", "unsil", "unjani", "widyatama", "itenas", "itn", "itats",
    "unusa", "unitomo", "untag", "uwks", "uty", "umby", "unisa", "upgris", "udinus", "unisbank", "usm", "unika",
    "unitri", "uinsu", "uinsgd", "uinsuka", "uinjkt", "uinarraniry", "uinalauddin", "uinradenfatah", "uinwalisongo", "uinantasari", "uinib", "uinmataram", "uinrms", "uinsatu", "uinfas", "uindatokarama", "uinsyahada", "uinbukittinggi", "uinpekalongan", "uinsalatiga", "uinkhas", "unirow", "unmas", "undiknas", "unhi", "unizar", "unidayan", "unibos", "umi", "uit", "unimed", "unpam", "unp", "uir", "unm", "unj", "untidar", "uniska", "uniku", "unibba", "unigal", "unipa", "unmus", "unkhair", "unsulbar", "unimor",
    "unismuh", "unipma", "unidha", "unbari", "unhaz", "unikal", "unikama", "uniks", "unilak", "unimar", "unimas", "uninus", "unipdu", "unira", "univrab", "unwiku", "unwir", "unwim", "unwira", "unuja", "unugiri",
    "polines", "polban", "polinema", "pens", "ppns", "polije", "polibatam", "polmed", "polsri", "pnp", "pnj", "pnb", "pnl", "politala", "polindra", "polman", "polimdo", "polnep", "polbeng",
    "talenta publisher", "badan penerbit fhui", "badan penerbit fkui", "badan penerbit universitas", "badan penerbit undip", "badan penerbit unm", "badan penerbit isi", "badan penerbitan"
])

SOC_PATTERN = compile_word_boundary_regex([
    "institute of advanced engineering and science", "iaes", "ieee", "acm",
    "asosiasi", "association", "perhimpunan", "ikatan", "himpunan", "masyarakat",
    "persatuan", "konsorsium", "consortium", "perkumpulan", "forum", "society", "aliansi", "alliance",
    "aptisi", "aptikom", "aptik", "adpi", "adrii", "adri", "relawan jurnal", "rji",
    "aipki", "aipni", "aipkind", "aipgi", "aptfi", "apdfi", "afeb", "forkomsii", "fppti", "appti", "apjiki",
    "idi", "ppni", "ibi", "hki", "pbi", "pii", "isei", "hagi", "iagi", "perki",
    "perdossi", "perhati", "pdgi", "pogi", "idai", "papdi", "pabi", "persi", "iaki", "iakmi", "persagi", "pafi", "patelki", "pormiki",
    "himpsi", "hpsi", "hepi", "hiski", "aspikom", "aspi", "perhepi", "perhorti", "peragi", "perhimpi", "hiti", "hatti", "hipmi", "kadin", "mui", "ispi", "hisfarsi", "isfi",
    "organisasi profesi", "federasi", "federation", "kolegium", "collegium", "union", "komunitas", "jejaring", "jaringan", "kelompok studi",
    "badan kerja sama", "badan kerjasama", "bks-ptn", "bkstm",
    "lembaga pendidikan ma'arif", "lembaga pendidikan maarif", "ma'arif nu", "maarif nu", "ma'arif", "maarif",
    "nahdlatul ulama", "pbnu", "pwnu", "pcnu", "lakpesdam", "muhammadiyah", "pwm", "pdm", "aisyiyah",
    "majelis", "pgri", "igi", "dewan da'wah", "al-irsyad", "persis", "wahdah islamiyah", "hidayatullah", "mathla'ul anwar",
    "ikatan cendekiawan", "icmi", "akademi ilmu pengetahuan indonesia", "aipi"
])

COM_PATTERN = compile_word_boundary_regex([
    "pt", "cv", "ud", "firma", "perseroan", "publisher", "publishing", "press", "media", "penerbit",
    "yayasan", "foundation", "independent", "scad", "deepublish", "goodwood",
    "cendekia", "mandiri", "utama", "karya", "pustaka", "buku", "percetakan",
    "graha", "mitra", "solusi", "konsultan", "consultant", "training", "center", "centre",
    "lembaga kajian", "lembaga studi", "lembaga pengembangan", "lembaga riset", "rumah sakit", "klinik",
    "institute", "corp", "corporation", "ltd", "inc", "llc"
])

# v2.7: press kampus yang namanya digabung (mis. "Unpadpress", "Staiqodpress") -> HEI, sama seperti "UNPAD Press".
CAMPUS_PRESS_COMPOUND_RE = re.compile(
    r"^(?:stai|stain|stit|stie|stikes|stkip|stmik|stt|uin|iain|univ|un|poltek|ugm|ipb|itb|its)[a-z]{0,8}press$"
)
ENGLISH_PRIVATE_INSTITUTE_RE = re.compile(r"\binstitute\b", flags=re.IGNORECASE)
COLLAB_SPLIT_RE = re.compile(
    r"\b(?:bekerja\s*sama\s+dengan|kerja\s*sama\s+dengan|in\s+collaboration\s+with|in\s+association\s+with)\b",
    flags=re.IGNORECASE
)


def _classify_single_publisher_clause(low: str, url_low: str = "") -> Tuple[str, str]:
    has_true_campus = bool(TRUE_CAMPUS_ENTITY_PATTERN.search(low) or UNIV_PRESS_REGEX.search(low))
    has_gov = bool(GOV_PATTERN.search(low) or GOV_BADAN_SAFE_RE.search(low))

    if STARTS_WITH_PT_CV.search(low):
        return "COM", "Badan Usaha Penerbit Komersial PT/CV/UD (COM)"
    if low.startswith("yayasan ") and not has_true_campus:
        return "COM", "Yayasan Penerbit Independen Non-Kampus (COM)"
    if ENGLISH_PRIVATE_INSTITUTE_RE.search(low) and not has_true_campus:
        if not SOC_PATTERN.search(low) and not has_gov:
            return "COM", "Lembaga Penerbit Swasta / Private Institute (COM)"

    if STARTS_WITH_SOC_PREFIX.search(low):
        return "SOC", "Organisasi Profesi / Asosiasi Keilmuan (SOC)"
    if SOC_EXPLICIT_PATTERN.search(low) and not STARTS_WITH_HEI_OR_GOV.search(low):
        return "SOC", "Asosiasi Prodi / Forum Dekan / Komunitas Ilmiah (SOC)"

    if has_gov and not has_true_campus:
        return "GOV", "Instansi Pemerintah / Kementerian / Badan / Balai Riset (GOV)"

    if has_true_campus or HEI_PATTERN.search(low):
        return "HEI", "Institusi Pendidikan Tinggi / Unit Kampus / University Press (HEI)"

    if SOC_PATTERN.search(low):
        return "SOC", "Organisasi Profesi / Himpunan Ilmiah / Perkumpulan (SOC)"

    if COM_PATTERN.search(low):
        return "COM", "Penerbit Komersial / Yayasan / Swasta (COM)"

    if ".ac.id" in url_low or ".edu" in url_low:
        return "HEI", "Domain Kampus .ac.id/.edu (HEI)"
    if ".go.id" in url_low:
        return "GOV", "Domain Pemerintah .go.id (GOV)"
    if ".or.id" in url_low and "yayasan" not in low:
        return "SOC", "Domain Organisasi .or.id (SOC)"

    return "COM", "Entitas Penerbit Independen / Non-Kampus (COM)"


def resolve_publisher_type_deterministic(
    publisher_clean: str, publisher_raw: str = "", website_url: str = ""
) -> Tuple[str, str]:
    """Menentukan tipe penerbit secara deterministik dari teks nama penerbit SINTA (v2.6)."""
    clean_norm = re.sub(r"\s+", " ", (publisher_clean or "").strip()).lower()
    raw_norm = re.sub(r"\s+", " ", (publisher_raw or "").strip()).lower()
    if not clean_norm and not raw_norm:
        return "", "Tanpa Penerbit (Dikosongkan)"

    if clean_norm in VERIFIED_PUBLISHER_OVERRIDES:
        lbl = VERIFIED_PUBLISHER_OVERRIDES[clean_norm]
        return lbl, f"Verified Override ({lbl})"
    if raw_norm in VERIFIED_PUBLISHER_OVERRIDES:
        lbl = VERIFIED_PUBLISHER_OVERRIDES[raw_norm]
        return lbl, f"Verified Override ({lbl})"

    primary_text = clean_norm or raw_norm
    url_low = (website_url or "").lower()
    if CAMPUS_PRESS_COMPOUND_RE.match(primary_text):
        return "HEI", "University Press Kampus (nama digabung) (HEI)"

    clauses = COLLAB_SPLIT_RE.split(primary_text, maxsplit=1)
    if len(clauses) > 1 and len(clauses[0].strip()) >= 3:
        first_clause = clauses[0].strip()
        if first_clause in VERIFIED_PUBLISHER_OVERRIDES:
            lbl = VERIFIED_PUBLISHER_OVERRIDES[first_clause]
            return lbl, f"Verified Override ({lbl})"
        return _classify_single_publisher_clause(first_clause, url_low)

    return _classify_single_publisher_clause(primary_text, url_low)


# Pola stopword asli saat training (WAJIB identik 100% dengan saat training agar 0.0 train-serve skew)
_STOPWORDS_PATTERN = re.compile(
    r"\b(?:vol|no|edisi|seri|jurnal|journal|indonesian|indonesia|international|"
    r"nasional|ilmiah|of|and|dan|di|ke|dari|the|in|on|for|studies|study|review|"
    r"research|riset|kajian)\b",
    flags=re.IGNORECASE,
)

# Pola stopword kedua khusus untuk penjaga OOD (extract_informative_journal_text)
_OOD_STOPWORDS_PATTERN = re.compile(
    r"\b(?:vol|no|edisi|seri|jurnal|journal|indonesian|indonesia|international|"
    r"nasional|ilmiah|of|and|dan|di|ke|dari|the|in|on|for|studies|study|review|"
    r"research|riset|kajian|berkala|buletin|bulletin|media|wahana|prosiding|proceeding)\b",
    flags=re.IGNORECASE,
)


def classify_publisher_size_rule_based(total_journals: int) -> Tuple[str, str]:
    """Aturan ukuran penerbit: 0-10 Small, 11-99 Medium, >=100 Large."""
    if total_journals >= 100:
        return "Large", "Besar"
    if total_journals >= 11:
        return "Medium", "Menengah"
    return "Small", "Kecil"


def clean_journal_text_for_tfidf(journal_title: str) -> str:
    """Preprocessing fitur TF-IDF yang 100% identik dengan fungsi saat pelatihan model."""
    raw = (journal_title or "").strip().lower()
    if not raw:
        return ""
    stripped = _STOPWORDS_PATTERN.sub(" ", raw)
    combined = f"{stripped} {raw}".strip()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_\s\-']", " ", combined)).strip()


def extract_informative_journal_text(journal_title: str) -> str:
    """Mengekstrak token informatif judul jurnal menggunakan _OOD_STOPWORDS_PATTERN khusus penjaga OOD."""
    raw = (journal_title or "").strip().lower()
    if not raw:
        return ""
    stripped = _OOD_STOPWORDS_PATTERN.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_\s\-']", " ", stripped)).strip()
    tokens = [t for t in cleaned.split() if len(t) >= 3 and not t.isdigit()]
    return " ".join(tokens)


def publisher_subject_tokens(publisher_name: str) -> str:
    """
    Token nama penerbit untuk model SUBJEK, diberi awalan "pub" agar terpisah dari kata judul
    (mis. "Fakultas Kedokteran Univ. X" -> "pubfakultas pubkedokteran pubuniv"). Nama penerbit sering
    menunjukkan bidang (Fakultas Ekonomi, STIKES, Fakultas Pertanian) saat judul jurnal tidak informatif.
    """
    words = re.sub(r"[^a-z0-9\s]", " ", (publisher_name or "").lower()).split()
    return " ".join("pub" + w for w in words if len(w) >= 3 and not w.isdigit())


def build_subject_text(journal_title: str, publisher_name: str = "") -> str:
    """Teks fitur model subjek v2.6 (identik saat training & serving): judul bersih + token nama penerbit."""
    return f"{clean_journal_text_for_tfidf(journal_title)} {publisher_subject_tokens(publisher_name)}".strip()


# ==============================================================================
# v2.7: KAMUS AKAR KATA BIDANG ILMU + TEKS FITUR MODEL SUBJEK SINTA (identik saat training & serving)
# ==============================================================================
# ---------------------------------------------------------------------------------------------
# Kamus akar kata per kelompok bidang. Pola regex huruf kecil; "\b" di depan = harus di awal kata.
# Akar panjang (>= 5 huruf) sengaja tanpa "\b" agar tertangkap di dalam kata bentukan.
# ---------------------------------------------------------------------------------------------
SUBJECT_LEXICON: Dict[str, List[str]] = {
    "health_med": [
        r"\bmedi[ck]", r"medis\b", r"medika", r"medicin", r"kedokteran", r"\bdokter", r"\bklini[ks]", r"clinic",
        r"rumah sakit", r"hospital", r"husada", r"\bsehat", r"kesehatan", r"health", r"\bkesmas", r"\bnakes",
        r"epidemiol", r"patolog", r"patholog", r"kardio", r"cardio", r"\bneuro", r"onkolog", r"oncolog",
        r"pediatri", r"paediatri", r"\bbedah", r"surg[ie]", r"\banest", r"radiolog", r"respir", r"pulmo",
        r"gastro", r"hepato", r"nefrolog", r"nephrolog", r"\burolog", r"dermato", r"oftalmo", r"ophthalm",
        r"ortoped", r"orthop", r"obstetr", r"ginekolog", r"gyn[ae]+col", r"psikiatr", r"psychiatr",
        r"\bimun", r"\bimmun", r"infeksi", r"infect", r"virolog", r"vaksin", r"vaccin", r"diabet",
        r"hipertensi", r"hypertens", r"stunting", r"covid", r"\bhiv\b", r"kanker", r"cancer", r"tumor",
        r"jantung", r"\bstroke", r"rehabilit", r"fisioterap", r"physiother", r"okupasi", r"medula",
        r"medicus", r"\bkes\b", r"biomedi", r"anatomi", r"anatomy", r"fisiolog", r"physiolog",
        r"\bdarah", r"hematolog", r"haematolog", r"endokrin", r"endocrin", r"geriatri", r"lansia",
    ],
    "nursing_midwifery": [
        r"\bnurs", r"perawat", r"keperawatan", r"\bners\b", r"\bbidan", r"kebidanan", r"midwi",
        r"maternal", r"neonat", r"\bibu dan anak", r"maternity",
    ],
    "pharmacy": [
        r"farmasi", r"pharma", r"\bfarma", r"\bobat", r"\bdrug", r"apotek", r"apothec", r"herbal",
        r"fitofarm", r"phytopharm", r"toksik", r"toxic", r"kosmetik", r"cosmet", r"\bjamu\b", r"farmakolog",
        r"pharmacolog",
    ],
    "dentistry": [r"\bdento", r"maksilo", r"maxillo", r"\bgigi", r"dental", r"dentist", r"odont", r"ortodon", r"periodon", r"\boral\b"],
    "nutrition": [r"\bgizi", r"nutri", r"\bdiet", r"dietetik", r"dietetic"],
    "public_health": [
        r"kesehatan masyarakat", r"public health", r"sanitasi", r"sanitation", r"promosi kesehatan",
        r"health promotion", r"kesehatan lingkungan", r"environmental health", r"occupational",
        r"keselamatan dan kesehatan kerja", r"\bk3\b", r"\bkesling",
    ],
    "psychology": [
        r"psikolog", r"psycholog", r"\bpsiko", r"\bpsycho", r"\bmental", r"kesehatan jiwa", r"\bjiwa\b",
        r"perilaku", r"behavio", r"well ?being", r"\bpsi\b", r"mediapsi", r"ecopsy",
    ],
    "sport": [
        r"olahraga", r"\bsport", r"\bpenjas", r"jasmani", r"kepelatihan", r"coaching", r"keolahragaan",
        r"sepak ?bola", r"football", r"futsal", r"\batlet", r"athlet", r"kinesiolog", r"physical education",
        r"rekreasi", r"recreation", r"\bsenam", r"fitness",
    ],
    "education": [
        r"pendidik", r"\bdidik", r"edukasi", r"edukat", r"educat", r"\bedu", r"pembelajaran", r"\bbelajar",
        r"learning", r"teaching", r"pengajaran", r"\bajar\b", r"\bguru\b", r"teacher", r"sekolah", r"school",
        r"kurikul", r"curricul", r"pedagog", r"didakt", r"didact", r"\bpaud\b", r"usia dini", r"early childhood",
        r"\bsiswa", r"\bstudent", r"keguruan", r"kependidikan", r"instruksional", r"instruction",
        r"\btadris", r"tarbiy", r"tarbaw", r"ta'lim", r"\btalim", r"\btadib", r"ta'dib", r"madrasah",
        r"asesmen", r"assessment", r"literasi", r"literacy", r"vokasi", r"vocation", r"kejuruan",
        r"inklusi", r"inclusive education", r"luar biasa", r"elementary", r"sekolah dasar", r"ibtidaiyah",
        r"mualim", r"muallim", r"mu'allim", r"kemahasiswaan", r"pengajar", r"\bpgsd", r"\bpgmi",
    ],
    "counseling": [r"konseling", r"counsel", r"bimbingan", r"guidance", r"irsyad"],
    "religion_islam": [
        r"islam", r"muslim", r"syari", r"sharia", r"shari'a", r"\bfiq[h]?", r"fikih", r"fiqih", r"\bhadi[st]",
        r"hadith", r"qur'?an", r"\bqur", r"tafsir", r"da'?wah", r"dakwah", r"tasawu", r"\bsufi", r"akidah",
        r"aqidah", r"\bushul", r"ushuluddin", r"muamalah", r"mu'amalah", r"\bzakat", r"wakaf", r"waqf",
        r"\bhalal", r"\bhaji\b", r"\bhajj", r"umrah", r"ibadah", r"\bilahi", r"tauhid", r"tawhid", r"\bkalam\b",
        r"\bfalak", r"nabawi", r"sunnah", r"\bulum", r"ma'?had", r"\bsantri", r"pesantren", r"\bkiai", r"\bkyai",
        r"\bulama", r"\bummah", r"\bumma[th]", r"\bumat\b", r"rabbani", r"\bsalaf", r"dirasa[th]", r"maqa[s]?shid",
        r"maqasid", r"\bsiyar\b", r"siyasa", r"jinayah", r"jinayat", r"munakahat", r"\bahwal", r"mawaris",
        r"faraid", r"baitul", r"masjid", r"mosque", r"\bhikma", r"\bturats", r"\bihya", r"\bagama", r"\brelig",
        r"keagamaan", r"\basnaf", r"\biman\b", r"akhlak", r"akhlaq", r"\bmuhammad", r"aswaja", r"\bnahdl", r"tarjih",
    ],
    "religion_christian": [
        r"teolog", r"theolog", r"kristen", r"christ", r"gereja", r"church", r"\binjil", r"gospel", r"alkitab",
        r"\bbibl", r"pastoral", r"diakon", r"\bmisi\b", r"misiolog", r"missiolog", r"misioner", r"missionar",
        r"apokal[iu]p", r"eskatolog", r"eschatolog", r"katek", r"katolik", r"catholic", r"salvation", r"rohani",
        r"kerygma", r"\bpneuma", r"\bagape", r"\bshalom", r"koinonia", r"kenosis", r"evangel", r"\bpastor",
    ],
    "religion_other": [
        r"\bhindu", r"buddh", r"\bbudha", r"\bdharma", r"\bdarma\b", r"\bweda", r"\bveda", r"konghucu",
        r"confucian", r"brahma", r"vihara", r"\bjnana", r"agama hindu", r"\bkhonghucu",
    ],
    "arabic_morph": [
        r"^(?:al|el|an|ar|as|at|ad|ash|ats|adz|az)[\s\-']", r"\b(?:al|el)[\s\-']\w", r"\w{3,}una\b",
        r"\w{2,}iyy?ah\b", r"\w{2,}iyy?at\b", r"\w{3,}aat\b", r"\w{3,}inaa?\b", r"\bdar\s?al",
    ],
    "law": [
        r"\bhukum", r"\blaw\b", r"\blaws\b", r"\blegal", r"legis", r"\bjuris", r"juridi", r"yuridi", r"\biuris",
        r"iurid", r"yusti", r"justi[sc]", r"justitia", r"keadilan", r"peradilan", r"pengadilan", r"\bcourt", r"pidana",
        r"criminal", r"perdata", r"notari", r"notary", r"advokat", r"advocat", r"konstitusi", r"constitut",
        r"perundang", r"\bundang", r"regulas", r"regulat", r"litigasi", r"litigat", r"arbitras", r"kontrak",
        r"contract", r"agraria", r"\blex\b", r"\bjure\b", r"\brecht", r"\bius\b", r"hak asasi", r"human rights",
        r"diskresi", r"anayasa", r"normatif", r"mercatoria", r"\bkenotariatan", r"kriminolog", r"criminolog",
        r"\bpolisi", r"kepolisian", r"\bjaksa", r"kejaksaan", r"legislat", r"\bpidana",
    ],
    "politics_gov": [
        r"politik", r"politic", r"pemerintah", r"govern", r"administrasi publik", r"public admin",
        r"administrasi negara", r"kebijakan", r"\bpolicy", r"birokra", r"bureaucr", r"otonomi", r"sentralis",
        r"pemilu", r"election", r"demokras", r"democra", r"parlemen", r"diplomas", r"diplomac",
        r"hubungan internasional", r"international relations", r"international studies", r"geopolit",
        r"pertahanan", r"defen[cs]e", r"ketahanan", r"keamanan", r"security", r"militer", r"military",
        r"intelijen", r"intelligence studies", r"\bpraja", r"pamong", r"\bdesa\b", r"village", r"bestuur",
        r"\bpublik\b", r"public sector", r"interdependen", r"\bnegara\b", r"\bstate\b",
    ],
    "communication_media": [
        r"komunikasi", r"communicat", r"jurnalistik", r"jurnalis\b", r"journalis", r"broadcast", r"penyiaran",
        r"\bsiaran", r"televisi", r"televis", r"public relation", r"\bhumas", r"periklanan", r"advertis",
        r"kehumasan", r"audience", r"komunikata", r"aspikom", r"\bpers\b", r"new media", r"mass media", r"media massa",
    ],
    "sociology_anthro": [
        r"sosiolog", r"sociolog", r"\bsosial", r"\bsocial", r"antropolog", r"anthropolog", r"masyarakat",
        r"society", r"societ", r"komunitas", r"community", r"gender", r"perempuan", r"\bwomen", r"feminis",
        r"keluarga", r"\bfamily", r"kemiskinan", r"poverty", r"kesejahteraan", r"welfare", r"demograf",
        r"demograph", r"kependudukan", r"populasi", r"population", r"migrasi", r"migration", r"pedesaan",
        r"\brural", r"pembangunan", r"develop", r"pekerja sosial", r"social work", r"humanitar",
        r"kemanusiaan", r"\bpuan\b", r"\banak\b", r"\bchild", r"pemuda", r"\byouth", r"disabilit",
        r"difabel", r"konflik", r"conflict", r"perdamaian", r"\bpeace", r"populika",
    ],
    "economy_business": [
        r"ekonom", r"econom", r"\bbisnis", r"business", r"manajemen", r"managem", r"akuntan", r"akuntansi",
        r"accounting", r"accountan", r"keuangan", r"financ", r"perbankan", r"banking", r"\bbank", r"\bpajak",
        r"\btax", r"taxation", r"pemasaran", r"marketing", r"wirausaha", r"entrepreneur", r"koperasi",
        r"investas", r"\binvest", r"\bsaham", r"stock", r"pasar modal", r"capital market", r"\bumkm", r"msme",
        r"fiskal", r"fiscal", r"moneter", r"monetar", r"\baudit", r"perpajakan", r"asuransi", r"insuran",
        r"\britel", r"retail", r"perdagangan", r"\btrade", r"ekspor", r"export", r"impor\b", r"import\b",
        r"supply chain", r"rantai pasok", r"\bsdm\b", r"human resource", r"sumber daya manusia",
        r"organisasi", r"organizat", r"kepemimpinan", r"leadership", r"\becobus", r"\bekobis", r"\bekonomi",
        r"laundering", r"\bjamsostek", r"probisnis", r"\bkoperasi", r"\bharga\b", r"\bprice", r"\bekbis",
        r"\bmanagerial", r"\bmanajerial", r"\bekuitas", r"\bequity", r"\bpasar\b", r"\bmarket\b", r"\bcuan",
    ],
    "tourism_hospitality": [
        r"pariwisata", r"wisata", r"tourism", r"touris", r"hospitality", r"perhotelan", r"\bhotel",
        r"kuliner", r"culinar", r"\btravel", r"destinasi", r"destination",
    ],
    "language_literature": [
        r"bahasa", r"language", r"linguist", r"linguis", r"\blingu", r"sastra", r"literat", r"literary",
        r"filolog", r"philolog", r"terjemah", r"translat", r"\blisan", r"lughah", r"lughaw", r"lughat",
        r"\barab", r"english", r"inggris", r"\btefl", r"\btesol", r"\befl\b", r"\besl\b", r"\bjawa\b",
        r"javan", r"sunda", r"melayu", r"\bmalay", r"\bbali\b", r"\bbugis", r"mandarin", r"chinese",
        r"\bchina\b", r"japan", r"jepang", r"nihon", r"korea", r"jerman", r"german", r"deutsch", r"perancis",
        r"french", r"fran[cç]ais", r"russian", r"spanish", r"belanda", r"dutch", r"bilingu", r"multilingu",
        r"wacana", r"discourse", r"semiot", r"pragmat", r"semant", r"morfolog", r"morpholog", r"fonolog",
        r"phonolog", r"sintaks", r"syntax", r"dialek", r"dialect", r"leksikograf", r"lexicograf", r"lexicograph",
        r"kamus", r"dictionar", r"\bpuisi", r"poetry", r"\bpoem", r"\bprosa", r"\bnovel", r"\bklausa",
        r"\bbahas\b", r"vernacular", r"\blingua", r"\bkata\b", r"\bword", r"\bteks\b", r"\btext\b",
        r"\bretorika", r"rhetoric", r"\bdeutsch", r"\bjapanolog", r"sinolog",
    ],
    "history_philosophy_culture": [
        r"sejarah", r"histor", r"filsafat", r"philosoph", r"filosof", r"budaya", r"cultur", r"kebudayaan",
        r"arkeolog", r"archaeolog", r"archeolog", r"tradisi", r"tradition", r"folklor", r"\badat\b", r"etnograf",
        r"ethnograph", r"warisan", r"heritage", r"humaniora", r"humanit", r"mitolog", r"mytholog", r"peradaban",
        r"civiliz", r"museum", r"naskah", r"manuscript", r"epigraf", r"prasasti", r"kearifan lokal",
        r"local wisdom", r"javanolog", r"diakroni", r"diachron", r"dekonstruk", r"deconstruct", r"\bepistem",
        r"sapientia", r"\betika\b", r"\bethics", r"hermeneut", r"\bnusantara", r"\bmelayu", r"\betnis",
        r"\bethnic", r"\bkajian budaya", r"\bcultural",
    ],
    "art_design": [
        r"\bseni\b", r"\bseni ?rupa", r"\bart(?!ikel|icle)", r"artistic", r"\bmusik", r"\bmusic", r"musikolog",
        r"\btari\b", r"\btarian", r"\bdance", r"teater", r"theat(?:re|er)", r"\brupa\b", r"desain", r"design",
        r"\bkriya", r"\bcraft", r"\bfilm", r"sinema", r"cinema", r"animasi", r"animat", r"fotograf",
        r"photograph", r"karawitan", r"pedalangan", r"wayang", r"\bbatik", r"\bukir", r"kerajinan", r"estetik",
        r"aesthet", r"interior", r"fashion", r"busana", r"tata rias", r"make ?up", r"\bvisual", r"kreatif",
        r"creativ", r"\btvf\b", r"sinektik", r"\bpertunjukan", r"performing", r"\bgame\b", r"\bkomik", r"\bcomic",
    ],
    "computing": [
        r"informatika", r"informat", r"komputer", r"comput", r"sistem informasi", r"information system",
        r"perangkat lunak", r"software", r"jaringan", r"network", r"internet", r"\biot\b", r"\bdata\b",
        r"basis data", r"database", r"kecerdasan buatan", r"artificial intelligence", r"\bai\b",
        r"machine learning", r"deep learning", r"\bcyber", r"\bsiber", r"\bdigital", r"multimedia", r"\bict\b",
        r"teknologi informasi", r"information technolog", r"\binfotek", r"\binfo", r"ilkom", r"ilmu komputer",
        r"\bsisfo", r"\bpemrograman", r"programming", r"algoritm", r"algorithm", r"\brobot", r"\bkomtek",
        r"intelmatic", r"\binfokum", r"\bsinus\b", r"\btechno", r"\btech\b", r"\bsistem\b", r"\bsystem",
        r"\baplikasi", r"\bapplication", r"\bsmart\b", r"\bblockchain", r"\bcloud\b", r"\bmobile\b",
        r"\btik\b", r"\bit\b", r"\bkomputasi", r"\bcomputa",
    ],
    "eng_electrical_mechanical": [
        r"\belektro", r"electr", r"elektron", r"listrik", r"\bpower\b", r"energi", r"energy", r"\btenaga",
        r"\bmesin", r"machin", r"mekanik", r"mechanic", r"mekatron", r"mechatron", r"otomas", r"automat",
        r"kontrol", r"control", r"instrumen", r"instrument", r"telekomunik", r"telecommun", r"sinyal",
        r"signal", r"antena", r"antenna", r"\bkilat\b", r"\bsutet\b", r"luceat", r"doppler", r"spektr",
        r"termal", r"thermal", r"fluida", r"\bfluid", r"tribolog", r"manufaktur", r"manufactur", r"industri",
        r"industr", r"ergonom", r"material", r"metalurg", r"metallurg", r"korosi", r"corros", r"otomotif",
        r"automotive", r"kendaraan", r"vehicle", r"aeronaut", r"aerospace", r"dirgantara", r"penerbangan",
        r"aviation", r"perkapalan", r"\bnaval", r"\bkapal\b", r"\bship", r"nuklir", r"nuclear", r"renewable",
        r"terbarukan", r"\bsurya\b", r"\bsolar\b", r"\bteknik\b", r"engineer", r"rekayasa", r"\bteknolog",
        r"technolog", r"\bteknisi", r"\btekno", r"\btechne",
    ],
    "eng_civil_architecture": [
        r"\bsipil", r"\bcivil\b", r"konstruksi", r"construct", r"struktur", r"structur", r"\bbeton",
        r"concrete", r"geotekn", r"geotechn", r"hidrolik", r"hydraul", r"hidrolog", r"hydrolog", r"jalan raya",
        r"highway", r"jembatan", r"bridge", r"transportas", r"transport", r"lalu lintas", r"traffic",
        r"arsitektur", r"architect", r"planolog", r"perencanaan wilayah", r"tata kota", r"\burban",
        r"\bkota\b", r"regional planning", r"wilayah dan kota", r"permukiman", r"settlement", r"perumahan",
        r"housing", r"lanskap", r"landscape", r"statika", r"\bspektran", r"\bbangunan", r"\bbuilding",
        r"\bsumber daya air", r"water resource", r"\bpantai", r"\bplano", r"\bgeometri jalan",
    ],
    "eng_chemical_mining": [
        r"teknik kimia", r"chemical engineering", r"distilasi", r"distillat", r"\bpetro", r"\bmigas",
        r"\bminyak", r"oil and gas", r"petroleum", r"perminyakan", r"pertambangan", r"tambang", r"\bmining",
        r"\bgas\b", r"batubara", r"\bcoal", r"\bproses\b", r"\bprocess", r"\breaktor", r"\breactor",
        r"\bmineral", r"\bpolimer", r"\bpolymer",
    ],
    "earth_geomatics": [
        r"geolog", r"geofisik", r"geophys", r"geomatik", r"geomatic", r"geodes", r"geospas", r"geospat",
        r"pemetaan", r"\bmapping", r"kartograf", r"cartograph", r"penginderaan jauh", r"remote sensing",
        r"\bgis\b", r"hidrograf", r"hydrograph", r"oseanograf", r"oceanograph", r"meteorolog", r"klimatolog",
        r"\bclimat", r"\biklim", r"atmosfer", r"atmospher", r"bencana", r"disaster", r"\bgempa", r"earthquake",
        r"vulkan", r"volcan", r"limnolog", r"geografi", r"geograph", r"\bbumi\b", r"\bearth\b", r"\bkebumian",
    ],
    "math_stats": [
        r"matemati", r"mathemat", r"\bmath", r"statisti", r"aktuari", r"actuari", r"aljabar", r"algebra",
        r"kalkulus", r"calculus", r"geometri", r"geometr", r"diferensial", r"differential", r"\bintegral",
        r"aritmati", r"arithmet", r"numerik", r"numeric", r"probabil", r"\bvariabel", r"cartesi", r"ekstrapol",
        r"extrapol", r"matika\b", r"\bnumber", r"\bbilangan", r"\bfungsi\b", r"\bkuantitatif", r"quantitativ",
        r"\binfinit", r"\bstatistik", r"kombinator", r"combinator", r"\blinear", r"\bpersegi", r"\bgraf\b", r"graph theory", r"\bmatriks", r"\bmatrix",
    ],
    "natural_science": [
        r"fisika", r"physic", r"\bkimia", r"chemi", r"\bchem\b", r"biolog", r"\bbio", r"botan", r"zoolog",
        r"\bzoo\b", r"ekolog", r"ecolog", r"mikrobiol", r"microbiol", r"genetik", r"\bgenet", r"bioteknol",
        r"biotechnol", r"biodivers", r"\bhayati", r"\bflora", r"\bfauna", r"entomol", r"iktiolog", r"ichthyolog",
        r"herpetolog", r"ornitolog", r"ornitholog", r"mikolog", r"mycolog", r"fikolog", r"phycolog", r"primat",
        r"\bsatwa", r"wildlife", r"konservasi", r"conserv", r"\bsains\b", r"science", r"scien", r"\bipa\b",
        r"\bmipa\b", r"\balam\b", r"\bnature", r"\bnatural", r"molekul", r"molecul", r"\bsel\b", r"\bcell",
        r"protein", r"\benzim", r"enzym", r"laborator", r"lantanid", r"lanthanid", r"kuantum", r"quantum",
        r"\boptik", r"\boptic", r"spektro", r"spectro", r"\bnano", r"astronom", r"kosmolog", r"cosmolog",
        r"ecophysiol", r"ekofisiol", r"\bzarah\b", r"\bpartikel", r"\bparticle", r"\bsains", r"\bsainstek", r"\bsaintek", r"\bmikro", r"\bmicro",
        r"\bkuman", r"\bvirus", r"\bbakteri", r"\bbacteri", r"\bjamur", r"\bfungi", r"\btumbuhan", r"\bplant",
        r"\bhewan", r"\banimal",
    ],
    "agriculture_crop": [
        r"pertanian", r"\bagri", r"\bagro", r"\bagron", r"\btani\b", r"\bpetani", r"\bfarm(?!a)", r"perkebunan",
        r"plantation", r"hortikult", r"horticult", r"tanaman", r"\bcrop", r"\btanah\b", r"\bsoil", r"\bbenih",
        r"\bseed", r"\bpupuk", r"fertiliz", r"irigasi", r"irrigat", r"agribisnis", r"agribusiness",
        r"pascapanen", r"postharvest", r"post-harvest", r"\bgulma", r"\bweed", r"\bhama\b", r"\bpest\b",
        r"\bpadi\b", r"\brice\b", r"\bsawit", r"palm oil", r"\bkopi\b", r"coffee", r"\bkakao", r"cocoa",
        r"\bkaret\b", r"rubber", r"\btebu\b", r"sugarcane", r"agroteknolog", r"agroekotek", r"agercolere",
        r"wanatani", r"\bagrotek", r"palawija", r"\bsayur", r"vegetable", r"\bbuah\b", r"\bfruit", r"\blahan\b", r"\bgambut", r"\bpeat", r"\bbudidaya", r"\bcultivat",
    ],
    "animal_vet": [
        r"peternakan", r"\bternak", r"livestock", r"\banimal science", r"veteriner", r"veterin", r"kedokteran hewan",
        r"\bvet\b", r"\bunggas", r"poultry", r"\bsapi\b", r"cattle", r"\bkambing", r"\bayam\b", r"\bpakan",
        r"\bfeed\b", r"\bpet\b", r"\bzoote", r"\bhusbandry",
    ],
    "fisheries_marine": [
        r"perikanan", r"\bikan\b", r"\bfish", r"akuakult", r"aquacult", r"perairan", r"aquatic", r"akuatik",
        r"kelautan", r"\bmarine", r"\blaut\b", r"\bsea\b", r"\bocean", r"pesisir", r"coastal", r"mangrove",
        r"terumbu", r"\bcoral", r"plankton", r"\bnekton", r"barakuda", r"marinade", r"hidrobiolog",
        r"\bbahari", r"maritim", r"maritime", r"waterway", r"\bsungai", r"\briver", r"\bdanau", r"\btambak", r"\budang", r"\bshrimp", r"\brumput laut", r"seaweed",
    ],
    "forestry": [
        r"kehutanan", r"\bhutan", r"\bforest", r"\bsylva", r"silvikult", r"agroforest", r"\bkayu", r"\bwood",
        r"\btimber", r"\beboni", r"\bwasian", r"\bdipterokarp", r"\bdipterocarp",
    ],
    "food_tech": [
        r"\bpangan", r"\bfood", r"teknologi pangan", r"food tech", r"pengolahan hasil", r"agroindustr",
        r"fermentas", r"ferment", r"bioindustr", r"\bolahan", r"\bboga\b", r"\bkuliner",
    ],
    "environment": [
        r"lingkungan", r"environment", r"sustainab", r"berkelanjutan", r"\blimbah", r"\bwaste", r"pencemaran",
        r"pollut", r"polusi", r"\bsampah", r"\bgreen", r"\bhijau", r"\bdas\b", r"\bair bersih",
    ],
    "library_information": [
        r"perpustakaan", r"\blibrar", r"kearsipan", r"\barchiv", r"\barsip", r"dokumentasi", r"\bpustaka",
        r"information science", r"ilmu informasi",
    ],
    "community_service": [
        r"pengabdian", r"\babdimas", r"\babdi", r"community service", r"community engagement", r"pemberdayaan",
        r"empowerment", r"\bdedikasi", r"\bkkn\b", r"\bpkm\b", r"\bmengabdi", r"\bservice learning",
    ],
    "general_research": [
        r"multidisiplin", r"multidisciplin", r"interdisiplin", r"interdisciplin", r"transdisiplin",
        r"penelitian", r"\bresearch", r"\briset", r"inovasi", r"innovat", r"\biptek", r"ilmu pengetahuan",
        r"sains dan teknologi", r"science and technology", r"\bterapan", r"\bapplied", r"\bilmiah",
        r"scientific", r"akademik", r"academic", r"cendekia", r"scholar", r"\bwawasan", r"\binsight",
        r"\bgeneral\b", r"\bumum\b",
    ],
}

_LEXICON_RE: Dict[str, "re.Pattern"] = {
    group: re.compile("|".join(f"(?:{p})" for p in patterns), flags=re.IGNORECASE)
    for group, patterns in SUBJECT_LEXICON.items()
}

# Nama penerbit yang hanya bersifat kelembagaan umum tidak dipakai sebagai petunjuk bidang dari kamus,
# kecuali ada kata bidang di dalamnya (mis. "Fakultas Kedokteran" -> health_med).
_NON_ALNUM_RE = re.compile(r"[^a-z0-9'\s\-]")
_SPACES_RE = re.compile(r"\s+")

# Stopword pembersih judul v2.6 (dipertahankan agar kosakata lama tetap berlaku)
_STOPWORDS_PATTERN_V27 = re.compile(
    r"\b(?:vol|no|edisi|seri|jurnal|journal|indonesian|indonesia|international|"
    r"nasional|ilmiah|of|and|dan|di|ke|dari|the|in|on|for|studies|study|review|"
    r"research|riset|kajian)\b",
    flags=re.IGNORECASE,
)


# Kata generik nama terbitan dibuang sebelum pencocokan kamus agar tidak menimbulkan salah tangkap pada
# pencocokan tanpa spasi (mis. "Jurnal Istiqro" -> "jurnalistiqro" tidak boleh terbaca "jurnalis").
_LEXICON_GENERIC_RE = re.compile(
    r"\b(?:jurnal|journal|journals|indonesian|indonesia|international|internasional|nasional|buletin|"
    r"bulletin|berkala|media|wahana|majalah|prosiding|proceedings?|of|and|dan|the|for|on|in|e|online|"
    r"vol|no|edisi|seri|jur|j)\b"
)


def normalize_text_for_lexicon(text: str) -> str:
    low = (text or "").lower().replace("\u2019", "'").replace("`", "'")
    low = _NON_ALNUM_RE.sub(" ", low)
    low = low.replace("-", " ")
    low = _LEXICON_GENERIC_RE.sub(" ", low)
    return _SPACES_RE.sub(" ", low).strip()


@lru_cache(maxsize=65536)
def lexicon_groups(text: str) -> Tuple[str, ...]:
    """Kelompok bidang yang cocok pada teks (urutan stabil sesuai SUBJECT_LEXICON). Hasil di-cache."""
    norm = normalize_text_for_lexicon(text)
    if not norm:
        return ()
    joined = norm.replace(" ", "")
    hits = []
    for group, rx in _LEXICON_RE.items():
        if rx.search(norm) or (group != "arabic_morph" and rx.search(joined) and _long_root_hit(rx, joined)):
            hits.append(group)
    return tuple(hits)


def _long_root_hit(rx: "re.Pattern", joined: str) -> bool:
    """Pada teks tanpa spasi, hanya terima kecocokan sepanjang >= 5 huruf (mencegah salah tangkap akar pendek)."""
    for m in rx.finditer(joined):
        if len(m.group(0)) >= 5:
            return True
    return False


def clean_title_v27(journal_title: str) -> str:
    raw = (journal_title or "").strip().lower()
    if not raw:
        return ""
    stripped = _STOPWORDS_PATTERN_V27.sub(" ", raw)
    combined = f"{stripped} {raw}".strip()
    return _SPACES_RE.sub(" ", re.sub(r"[^a-z0-9_\s\-']", " ", combined)).strip()


def publisher_tokens_v27(publisher_name: str) -> str:
    words = re.sub(r"[^a-z0-9\s]", " ", (publisher_name or "").lower()).split()
    return " ".join("pub" + w for w in words if len(w) >= 3 and not w.isdigit())


def publisher_key(publisher_name: str) -> str:
    """Kunci nama penerbit: huruf kecil + spasi diseragamkan (sama dengan kunci 'name:' v2.6)."""
    return _SPACES_RE.sub(" ", (publisher_name or "").strip().lower())


def publisher_prior_tokens(prior: Optional[Dict[str, float]]) -> str:
    """
    Token petunjuk dari sebaran subjek jurnal lain milik penerbit yang sama (mis. {"Health": 0.8, ...}).
    Diulang 1-4 kali sesuai porsinya; hanya subjek dengan porsi >= 15% yang dipakai.
    """
    if not prior:
        return ""
    out = []
    for subj, share in sorted(prior.items()):
        if share >= 0.15:
            tok = "pp_" + re.sub(r"[^a-z]", "", subj.lower())
            out.extend([tok] * (1 + min(3, int(share * 4))))
    return " ".join(out)


def build_subject_text_v27(
    journal_title: str,
    publisher_name: str = "",
    publisher_prior: Optional[Dict[str, float]] = None,
) -> str:
    """Teks fitur model subjek v2.7 = judul bersih + token penerbit + token kamus (judul & penerbit) + token prior."""
    title_groups = lexicon_groups(journal_title)
    pub_groups = [g for g in lexicon_groups(publisher_name) if g != "arabic_morph"]
    parts = [
        clean_title_v27(journal_title),
        publisher_tokens_v27(publisher_name),
        " ".join("lx_" + g for g in title_groups),
        " ".join("lxp_" + g for g in pub_groups),
        publisher_prior_tokens(publisher_prior),
    ]
    if not title_groups:
        parts.append("lx_none")
    return " ".join(p for p in parts if p).strip()


def parse_sinta_subjects(value: Any) -> List[str]:
    """Subjek SINTA asli (string "A, B" atau list) -> list subjek SINTA-10 yang valid, urutan dipertahankan."""
    if value is None:
        return []
    parts = value if isinstance(value, (list, tuple)) else str(value).split(",")
    out: List[str] = []
    for p in parts:
        name = str(p).strip()
        if name in SINTA_10_SUBJECTS and name not in out:
            out.append(name)
    return out


def _word_vectorizer(tfidf_step: Any) -> Any:
    """Ambil vektorisasi kata dari langkah tfidf (FeatureUnion 'word'+'char' pada v2.6, atau TfidfVectorizer biasa)."""
    if hasattr(tfidf_step, "transformer_list"):
        return dict(tfidf_step.transformer_list)["word"]
    return tfidf_step


def extract_publisher_lexical_signals(
    publisher_clean: str,
    publisher_raw: str = "",
    verified_overrides: Optional[Dict[str, str]] = None,
) -> str:
    """Mengekstrak teks murni nama penerbit untuk TF-IDF tanpa kebocoran label (identik saat train & serve -> selisih prob = 0.0)."""
    base_source = (publisher_clean or publisher_raw or "").strip().lower()
    if not base_source:
        return "no_publisher_empty"
    base_txt = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_\s\-'.]", " ", base_source)).strip()
    return base_txt if base_txt else "no_publisher_empty"


def _resolve_unified_publisher_groups(items: List[Dict[str, Any]]) -> Tuple[List[Tuple[str, bool]], Dict[str, int]]:
    """
    Menggabungkan baris yang merujuk ke PENERBIT YANG SAMA di seluruh request (sebelum dipotong per chunk),
    yaitu baris dengan nama penerbit ternormalisasi yang sama ATAU publisher_id yang sama.

    v2.6: `sinta_publisher_id` TIDAK lagi dipakai sebagai kunci penggabungan. Di data SINTA, kolom ini
    adalah ID afiliasi (satu ID dipakai hingga 58 nama penerbit berbeda), sehingga union-find lewat kolom
    ini menggabungkan penerbit yang tidak berhubungan (mis. Universitas Ahmad Dahlan dengan penerbit
    komersial) dan membuat hasil bergantung pada isi batch.

    Baris tanpa nama penerbit (kosong / "-" / "nan") diperlakukan sebagai tanpa penerbit walaupun
    memiliki publisher_id, karena tidak ada teks yang bisa diklasifikasikan.
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # Prioritaskan kunci berbasis name: sebagai root kanonik agar konsisten
            if ra.startswith("name:") and not rb.startswith("name:"):
                parent[rb] = ra
            elif rb.startswith("name:") and not ra.startswith("name:"):
                parent[ra] = rb
            elif ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    item_Initial_keys: List[Tuple[List[str], bool]] = []
    for idx, it in enumerate(items):
        pub_id = str(it.get("publisher_id") or "").strip()
        sinta_pub_id = str(it.get("sinta_publisher_id") or "").strip()
        p_clean = str(
            it.get("publisher_name_clean")
            or it.get("normalized_publisher_name")
            or ""
        ).strip()
        p_raw = str(
            it.get("publisher_name_raw")
            or it.get("publisher_name")
            or ""
        ).strip()

        if p_clean.lower() in {"nan", "none", "null", "-", "unknown", "#name?"}:
            p_clean = ""
        if p_raw.lower() in {"nan", "none", "null", "-", "unknown", "#name?"}:
            p_raw = ""
        if pub_id.lower() in {"nan", "none", "null", "-", "0"}:
            pub_id = ""
        if sinta_pub_id.lower() in {"nan", "none", "null", "-", "0"}:
            sinta_pub_id = ""

        if not p_clean and not p_raw:
            item_Initial_keys.append(([f"__no_publisher_{idx}__"], True))
            continue

        norm_name = re.sub(r"\s+", " ", (p_clean or p_raw).lower()).strip()
        keys_for_item: List[str] = [f"name:{norm_name}"]
        if pub_id:
            keys_for_item.append(f"id:{pub_id}")

        for k in keys_for_item:
            parent.setdefault(k, k)
        for k in keys_for_item[1:]:
            union(keys_for_item[0], k)

        item_Initial_keys.append((keys_for_item, False))

    resolved_keys: List[Tuple[str, bool]] = []
    pub_counts_in_batch: Dict[str, int] = {}
    for keys_list, is_no_pub in item_Initial_keys:
        if is_no_pub:
            resolved_keys.append((keys_list[0], True))
        else:
            canon_key = find(keys_list[0])
            resolved_keys.append((canon_key, False))
            pub_counts_in_batch[canon_key] = pub_counts_in_batch.get(canon_key, 0) + 1

    return resolved_keys, pub_counts_in_batch


def _patch_sklearn_compat(obj: Any) -> None:
    visited = set()

    def _walk(node: Any) -> None:
        if node is None or id(node) in visited:
            return
        visited.add(id(node))
        cls_name = type(node).__name__
        if cls_name == "MaxAbsScaler" and not hasattr(node, "clip"):
            setattr(node, "clip", False)
        if isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple, set)):
            for v in node:
                _walk(v)
        elif hasattr(node, "__dict__"):
            for v in vars(node).values():
                _walk(v)

    _walk(obj)


class _RestrictedModelUnpickler(pickle.Unpickler):
    """
    Unpickler aman (whitelist) yang memblokir eksekusi kelas/fungsi berbahaya (seperti os.system,
    subprocess, eval, exec) saat memuat berkas .pkl. Hanya mengizinkan kelas scikit-learn, numpy,
    scipy.sparse, dan tipe data bawaan Python yang aman.
    """
    _ALLOWED_BUILTINS: Set[str] = {
        "dict", "list", "tuple", "set", "frozenset", "str", "int", "float",
        "bool", "bytes", "bytearray", "complex", "slice", "object", "range",
    }
    _ALLOWED_MODULE_PREFIXES: Tuple[str, ...] = (
        "sklearn.",
        "numpy.",
        "scipy.sparse.",
    )
    _ALLOWED_EXACT_MODULES: Set[str] = {
        "sklearn",
        "numpy",
        "scipy.sparse",
        "collections",
        "copyreg",
        "_codecs",
    }

    def find_class(self, module: str, name: str) -> Any:
        if module == "builtins":
            if name in self._ALLOWED_BUILTINS:
                return super().find_class(module, name)
            raise pickle.UnpicklingError(
                f"Keamanan Pickle: Kelas builtins '{name}' tidak diizinkan dalam berkas model."
            )
        if module in self._ALLOWED_EXACT_MODULES or module.startswith(self._ALLOWED_MODULE_PREFIXES):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(
            f"Keamanan Pickle: Modul/kelas '{module}.{name}' diblokir karena bukan objek sklearn/numpy resmi."
        )


def _safe_load_pickle_bytes(raw_bytes: bytes) -> Any:
    return _RestrictedModelUnpickler(io.BytesIO(raw_bytes)).load()


class SClipsMLPredictor:
    """
    Mesin Prediksi Klasifikasi Penerbit & Subjek Jurnal S-CLIPS (v2.7).

    Kontrak v2.7 (perubahan dari v2.6):
    - TIDAK ADA label "Unknown". Setiap jurnal selalu mendapat subjek SINTA, rumpun Scopus, bidang Scopus-27,
      dan tipe penerbit. `is_ood = True` kini hanya catatan bahwa judul tidak memuat kata yang dikenal model;
      label tetap diberikan dari potongan huruf, kamus akar kata, dan nama penerbit.
    - `subject_label` = label subjek yang ditampilkan dengan keyakinan (`subject_label_confidence`) minimal 70%:
      satu subjek SINTA, atau dua subjek teratas bila satu subjek belum mencapai 70%. Keyakinan dikalibrasi
      terhadap subjek SINTA asli (peluang label yang ditampilkan memang subjek jurnal itu).
    - Bila input menyertakan `subject_sinta` (subjek SINTA asli), `subject_display` memakai subjek SINTA
      (>= 4 subjek -> "Multidisciplinary") dan bidang Scopus dibatasi ke bidang subjek tersebut.
    - Tipe penerbit tanpa "Unknown": nama tanpa kata dikenal -> aturan bawaan penerbit independen (COM);
      tanpa nama penerbit -> label mayoritas (HEI) dengan status Needs Review.
    - `processing_status = "Needs Review"` hanya bila keyakinan label subjek atau tipe penerbit < 70%,
      ada konflik aturan vs model, atau nama penerbit kosong. `review_reasons` menjelaskan alasannya;
      `notes` berisi catatan informatif yang tidak mengubah status.
    - Label satu jurnal tidak bergantung pada jurnal lain di batch yang sama.
    """
    _instance: Optional["SClipsMLPredictor"] = None
    _instance_lock = threading.RLock()

    def __init__(self, model_path: str, expected_sha256: Optional[str] = None):
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Berkas model '{model_path}' tidak ditemukan. Pastikan berkas model (.pkl) berada di direktori layanan."
            )

        with open(model_path, "rb") as f:
            raw_bytes = f.read()

        # Validasi Checksum SHA-256 SEBELUM unpickling (aktif secara default menggunakan DEFAULT_MODEL_SHA256)
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        allow_unverified = os.environ.get("SCLIPS_ALLOW_UNVERIFIED_PICKLE", "0").strip().lower() in {
            "1", "true", "yes"
        }
        target_sha = (expected_sha256 or os.environ.get("SCLIPS_MODEL_SHA256", "")).strip().lower()

        if target_sha:
            if actual_hash.lower() != target_sha:
                raise ValueError(
                    f"Checksum SHA-256 berkas model tidak cocok (diharapkan: {target_sha}, aktual: {actual_hash})."
                )
        elif not allow_unverified:
            if actual_hash.lower() not in KNOWN_VALID_MODEL_SHA256S:
                raise ValueError(
                    f"Checksum SHA-256 berkas model ({actual_hash}) tidak terdaftar dalam KNOWN_VALID_MODEL_SHA256S "
                    f"(DEFAULT_MODEL_SHA256={DEFAULT_MODEL_SHA256}). Set SCLIPS_MODEL_SHA256 jika menggunakan model baru."
                )

        # Unpickle melalui _RestrictedModelUnpickler agar bebas dari eksekusi kode berbahaya (arbitrary code execution)
        self.bundle = _safe_load_pickle_bytes(raw_bytes)
        if not isinstance(self.bundle, dict) or "publisher_type_pipeline" not in self.bundle:
            raise ValueError("Struktur berkas model .pkl tidak valid (bukan dictionary bundel S-CLIPS).")

        _patch_sklearn_compat(self.bundle)

        self.model_sha256: str = actual_hash
        self.model_version: str = self.bundle.get("model_version", "v2.7-unknown")
        self.trained_sklearn_version: str = str(
            self.bundle.get("trained_sklearn_version") or self.bundle.get("sklearn_version", "unknown")
        )
        self.runtime_sklearn_version: str = str(sklearn.__version__)

        # Peringatan keras / proteksi jika versi mayor.minor scikit-learn runtime berbeda dengan saat training
        trained_mm = ".".join(self.trained_sklearn_version.split(".")[:2])
        runtime_mm = ".".join(self.runtime_sklearn_version.split(".")[:2])
        if self.trained_sklearn_version != "unknown" and trained_mm != runtime_mm:
            msg = (
                f"PERINGATAN KOMPATIBILITAS SKLEARN: Model '{self.model_version}' dilatih pada "
                f"scikit-learn=={self.trained_sklearn_version}, tetapi runtime saat ini menggunakan "
                f"scikit-learn=={self.runtime_sklearn_version}."
            )
            warnings.warn(msg, RuntimeWarning, stacklevel=2)
            logger.warning(msg)
            if os.environ.get("SCLIPS_STRICT_SKLEARN_VERSION", "0").strip() in {"1", "true", "True"}:
                raise RuntimeError(msg)

        self.pub_pipe = self.bundle["publisher_type_pipeline"]
        self.scopus27_pipe = self.bundle.get("subject_scopus_27_pipeline")
        self.sinta_pipe = self.bundle["subject_sinta_pipeline"]
        self._validate_pipeline_classes()
        calib = self.bundle.get("subject_calibration") or {}
        for key in ("single", "pair", "rumpun"):
            if key not in calib:
                raise ValueError(f"Bundel model tidak memuat kalibrasi subjek '{key}' (wajib pada v2.7).")
        # Kalibrator dipisah: jurnal dari penerbit yang sudah punya jurnal berlabel ("known") vs penerbit baru ("new").
        self.calib = calib
        self.publisher_subject_prior: Dict[str, Dict[str, float]] = {
            str(k): {str(a): float(b) for a, b in v.items()}
            for k, v in (self.bundle.get("publisher_subject_prior") or {}).items()
        }
        fallback = self.bundle.get("publisher_fallback") or {}
        self.default_independent_conf: float = float(fallback.get("default_independent_conf", 74.0))
        self.no_name_label: str = str(fallback.get("no_name_label", "HEI"))
        self.no_name_conf: float = float(fallback.get("no_name_conf", 81.7))
        self.md_min_subjects: int = int(
            self.bundle.get("multidisciplinary_min_sinta_subjects", MULTIDISCIPLINARY_MIN_SINTA_SUBJECTS)
        )
        self.verified_overrides: Dict[str, str] = {
            **VERIFIED_PUBLISHER_OVERRIDES,
            **self.bundle.get("verified_publisher_overrides", {}),
        }
        # Hanya memuat publisher_db_counts berbasis nama penerbit utuh (tanpa key token: atau fallback IDF)
        raw_db_counts = self.bundle.get("publisher_db_counts", {})
        self.publisher_db_counts: Dict[str, int] = {
            str(k): int(v)
            for k, v in raw_db_counts.items()
            if not str(k).startswith("token:")
        }

        # Ambang batas confidence & multilabel dari optimal_thresholds di dalam .pkl
        opt_thresh = self.bundle.get("optimal_thresholds", {})
        self.pub_conf_threshold: float = float(
            opt_thresh.get("publisher_type_pct", DEFAULT_PUBLISHER_CONFIDENCE_THRESHOLD)
        )
        self.label_conf_threshold: float = float(
            opt_thresh.get("label_confidence_pct", DEFAULT_LABEL_CONFIDENCE_THRESHOLD)
        )
        self.scopus4_conf_threshold: float = float(
            opt_thresh.get("subject_scopus_4_pct", DEFAULT_SCOPUS4_CONFIDENCE_THRESHOLD)
        )
        self.sinta10_conf_threshold: float = float(
            opt_thresh.get("subject_sinta_10_pct", DEFAULT_SINTA10_CONFIDENCE_THRESHOLD)
        )
        self.scopus27_conf_threshold: float = float(
            opt_thresh.get(
                "subject_scopus_27_pct",
                opt_thresh.get("subject_sinta_10_pct", DEFAULT_SCOPUS27_CONFIDENCE_THRESHOLD),
            )
        )
        self.sinta_multilabel_prob_threshold: float = (
            float(opt_thresh.get("subject_sinta_multilabel_pct", DEFAULT_SINTA_MULTILABEL_THRESHOLD_PCT)) / 100.0
        )
        self.l2_norm = Normalizer(norm="l2")
        logger.info(
            "Model %s (SHA256: %s...) dimuat dari %s (sklearn train=%s, runtime=%s)",
            self.model_version,
            self.model_sha256[:12],
            model_path,
            self.trained_sklearn_version,
            self.runtime_sklearn_version,
        )

    @staticmethod
    def _pipe_classes(pipe: Optional[Dict[str, Any]]) -> List[str]:
        if pipe is None:
            return []
        if pipe.get("sklearn_pipeline") is not None:
            return [str(c) for c in pipe["sklearn_pipeline"].named_steps["clf"].classes_]
        return [str(c) for c in getattr(pipe.get("model"), "classes_", [])]

    def _validate_pipeline_classes(self) -> None:
        """
        Gagal keras saat startup bila kelas model tidak sesuai taksonomi (mis. ada kelas kosong '' seperti
        pada model v2.5). Lebih baik service menolak start daripada diam-diam mengeluarkan label kosong.
        """
        checks = [
            ("publisher_type_pipeline", self.pub_pipe, set(PUBLISHER_TYPES)),
            ("subject_sinta_pipeline", self.sinta_pipe, set(SINTA_10_SUBJECTS)),
            ("subject_scopus_27_pipeline", self.scopus27_pipe, set(SCOPUS_27_TO_INDONESIAN)),
        ]
        for name, pipe, allowed in checks:
            if pipe is None:
                continue
            classes = self._pipe_classes(pipe)
            bad = [c for c in classes if c not in allowed]
            if bad or len(classes) < 2:
                raise ValueError(
                    f"Kelas pada '{name}' tidak valid: {bad or classes}. Latih ulang model tanpa label kosong/asing."
                )

    def _lookup_historical_publisher_count(
        self, g_key: str, pub_id: str, sinta_pub_id: str, p_clean: str
    ) -> int:
        """
        Mencari jumlah jurnal penerbit di database SINTA berdasarkan kecocokan utuh nama penerbit
        ternormalisasi (`name:<full_name>`) atau publisher_id (`id:`). Ukuran penerbit = jumlah jurnal
        PER PENERBIT (bukan per institusi induk). `sinta_publisher_id` (ID afiliasi) tidak dipakai.
        Parameter `sinta_pub_id` dipertahankan hanya untuk kompatibilitas tanda tangan fungsi.
        """
        candidates: List[str] = [g_key]
        if pub_id:
            candidates.extend([f"id:{pub_id}", str(pub_id)])
        norm_name = re.sub(r"\s+", " ", (p_clean or "").lower()).strip()
        if norm_name:
            candidates.extend([f"name:{norm_name}", norm_name])

        best_cnt = 0
        for cand in candidates:
            if cand in self.publisher_db_counts:
                best_cnt = max(best_cnt, int(self.publisher_db_counts[cand]))
        return best_cnt

    @staticmethod
    def _compute_sha256(file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def get_instance(cls, model_path: Optional[str] = None) -> "SClipsMLPredictor":
        """Thread-safe Singleton dengan prioritas nama file MODEL_FILENAME_DEFAULT."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    candidates = [
                        os.path.join(base_dir, MODEL_FILENAME_DEFAULT),
                        os.path.join(base_dir, "sclips_models.pkl"),
                    ]
                    default_file = next((p for p in candidates if os.path.exists(p)), candidates[0])
                    resolved_path = model_path or os.environ.get("SCLIPS_MODEL_PATH", default_file)
                    expected_sha = os.environ.get("SCLIPS_MODEL_SHA256")
                    cls._instance = cls(resolved_path, expected_sha256=expected_sha)
        return cls._instance

    def _predict_proba_single_pass(
        self,
        pipe: Dict[str, Any],
        texts: List[str],
        default_classes: List[str],
        informative_texts: Optional[List[str]] = None,
    ) -> Tuple[np.ndarray, List[str], np.ndarray, Any]:
        """
        Menghitung transformasi TF-IDF satu kali saja per prediksi (single-pass),
        serta menghitung nnz pada teks informatif (_OOD_STOPWORDS_PATTERN) untuk penjaga OOD.
        """
        if "sklearn_pipeline" in pipe and pipe["sklearn_pipeline"] is not None:
            sk_pipe = pipe["sklearn_pipeline"]
            tfidf_step = sk_pipe.named_steps["tfidf"]
            scaler_step = sk_pipe.named_steps["scaler"]
            norm_step = sk_pipe.named_steps["norm"]
            clf_step = sk_pipe.named_steps["clf"]

            X_tfidf = tfidf_step.transform(texts)
            X_scaled = scaler_step.transform(X_tfidf)
            X_norm = norm_step.transform(X_scaled)
            probs = clf_step.predict_proba(X_norm)
            classes = list(clf_step.classes_)
        else:
            tfidf_step = pipe["vectorizer"]
            X_tfidf = tfidf_step.transform(texts)
            X_scaled = pipe["scaler"].transform(X_tfidf)
            norm_step = pipe.get("normalizer", self.l2_norm)
            X_norm = norm_step.transform(X_scaled) if norm_step is not None else X_scaled
            model = pipe["model"]
            probs = model.predict_proba(X_norm)
            classes = list(model.classes_) if hasattr(model, "classes_") else default_classes

        if informative_texts is not None:
            # Penjaga OOD hanya memakai vektorisasi KATA. Pada model v2.6, langkah "tfidf" subjek berupa
            # FeatureUnion kata + karakter; n-gram karakter hampir selalu cocok dengan teks apa pun sehingga
            # tidak boleh dipakai untuk menilai apakah judul dikenali.
            X_info = _word_vectorizer(tfidf_step).transform(informative_texts)
            nnz_counts = np.diff(X_info.tocsr().indptr)
        else:
            nnz_counts = np.diff(X_tfidf.indptr)

        return probs, classes, nnz_counts, X_norm

    def _predict_proba_with_ood(
        self,
        pipe: Dict[str, Any],
        texts: List[str],
        default_classes: Optional[List[str]] = None,
    ) -> Tuple[np.ndarray, List[str], np.ndarray]:
        """Alias kompatibilitas mundur (backward-compatible) untuk pemanggil eksternal."""
        probs, classes, nnz_counts, _ = self._predict_proba_single_pass(
            pipe, texts, default_classes or []
        )
        return probs, classes, nnz_counts

    def _publisher_prior(self, publisher_name: str) -> Optional[Dict[str, float]]:
        key = publisher_key(publisher_name)
        if not key:
            return None
        prior = self.publisher_subject_prior.get(key)
        return dict(prior) if prior else None

    def _calibrated(self, kind: str, score: float, has_prior: bool) -> float:
        cal = self.calib[kind]
        if isinstance(cal, dict):
            cal = cal["known" if has_prior and "known" in cal else "new"]
        return float(cal.predict([score])[0]) * 100.0

    def _subject_label_decision(
        self, probs_row: np.ndarray, classes: List[str], has_prior: bool = False
    ) -> Dict[str, Any]:
        """
        Keputusan label subjek bertingkat v2.7 (selalu menghasilkan label, tanpa "Unknown"):
          1) satu subjek SINTA bila P(benar) >= ambang (default 70%);
          2) dua subjek teratas bila P(salah satunya benar) >= ambang;
          3) rumpun ilmu (Scopus 4 rumpun) bila P(rumpun benar) >= ambang;
          4) bila tidak ada yang mencapai ambang: dua subjek teratas + status Needs Review.
        P(benar) berasal dari kalibrasi isotonik out-of-fold terhadap subjek SINTA asli (bukan probabilitas mentah).
        """
        order = np.argsort(-probs_row)
        top1, top2 = classes[int(order[0])], classes[int(order[1])]
        p1 = float(probs_row[order[0]])
        p12 = float(probs_row[order[0]] + probs_row[order[1]])
        rumpun_mass: Dict[str, float] = {}
        for j, c in enumerate(classes):
            r = SINTA_TO_SCOPUS_MAP[c]
            rumpun_mass[r] = rumpun_mass.get(r, 0.0) + float(probs_row[j])
        top_rumpun = max(sorted(rumpun_mass), key=lambda r: rumpun_mass[r])
        k1 = self._calibrated("single", p1, has_prior)
        k2 = self._calibrated("pair", p12, has_prior)
        kr = self._calibrated("rumpun", rumpun_mass[top_rumpun], has_prior)
        thr = self.label_conf_threshold
        if k1 >= thr:
            level, subjects, conf = LABEL_LEVEL_SUBJECT, [top1], k1
        elif k2 >= thr:
            level, subjects, conf = LABEL_LEVEL_PAIR, [top1, top2], k2
        elif kr >= thr:
            level, subjects, conf = LABEL_LEVEL_RUMPUN, [c for c in (top1, top2) if SINTA_TO_SCOPUS_MAP[c] == top_rumpun] or [top1], kr
        else:
            level, subjects, conf = LABEL_LEVEL_PAIR, [top1, top2], max(k1, k2, kr)
        if level == LABEL_LEVEL_RUMPUN:
            label = top_rumpun
            label_id = SCOPUS_4_TO_INDONESIAN.get(top_rumpun, top_rumpun)
        else:
            label = ", ".join(subjects)
            label_id = ", ".join(SINTA_TO_INDONESIAN.get(s, s) for s in subjects)
        return {
            "top1": top1, "top1_conf": round(k1, 2), "subjects": subjects, "level": level,
            "label": label, "label_id": label_id, "conf": round(conf, 2),
            "rumpun": top_rumpun if level == LABEL_LEVEL_RUMPUN else SINTA_TO_SCOPUS_MAP[top1],
            "rumpun_conf": round(kr if level == LABEL_LEVEL_RUMPUN else
                                 self._calibrated("rumpun", rumpun_mass[SINTA_TO_SCOPUS_MAP[top1]], has_prior), 2),
            "rumpun_mass": rumpun_mass,
        }

    def _pick_scopus27(
        self, probs27: Optional[np.ndarray], classes27: List[str], allowed: List[str]
    ) -> Tuple[Optional[str], Optional[float]]:
        """Bidang Scopus-27 dengan probabilitas tertinggi DI ANTARA bidang yang sah untuk label subjek terpilih."""
        if probs27 is None:
            return None, None
        allowed_set = set(allowed)
        best, best_p = None, -1.0
        for j, c in enumerate(classes27):
            if (not allowed_set or c in allowed_set) and float(probs27[j]) > best_p:
                best, best_p = c, float(probs27[j])
        if best is None:
            j = int(np.argmax(probs27)); best, best_p = classes27[j], float(probs27[j])
        return best, round(best_p * 100.0, 2)

    def predict_batch(
        self,
        items: List[Dict[str, Any]],
        publisher_counts_override: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        if not items:
            return []
        if len(items) > MAX_BATCH_SIZE:
            raise ValueError(f"Ukuran batch melebihi batas maksimum ({MAX_BATCH_SIZE} item).")

        use_rules = os.environ.get("SCLIPS_USE_RULES", "1").strip() not in {"0", "false", "False"}
        ext_counts = publisher_counts_override or {}
        group_keys, pub_counts_in_batch = _resolve_unified_publisher_groups(items)

        pub_texts: List[str] = []
        subject_texts_v27: List[str] = []
        subject_texts_v26: List[str] = []
        informative_journal_texts: List[str] = []
        parsed_origins: List[Dict[str, Any]] = []
        group_max_total: Dict[str, int] = {}

        for idx, it in enumerate(items):
            j_title = str(it.get("journal_title") or it.get("journal_name") or "").strip()
            p_raw = str(it.get("publisher_name_raw") or it.get("publisher_name") or "").strip()
            p_clean = str(
                it.get("publisher_name_clean")
                or it.get("normalized_publisher_name")
                or p_raw
            ).strip()
            if p_clean.lower() in {"nan", "none", "null", "-", "unknown", "#name?"}:
                p_clean = ""
            if p_raw.lower() in {"nan", "none", "null", "-", "unknown", "#name?"}:
                p_raw = ""

            pub_id = it.get("publisher_id")
            pub_id_str = "" if pub_id is None or str(pub_id).strip().lower() in {"", "nan", "none", "null", "0"} else str(pub_id).strip()
            sinta_pub_id = str(it.get("sinta_publisher_id") or "").strip()
            if sinta_pub_id.lower() in {"nan", "none", "null", "-", "0"}:
                sinta_pub_id = ""

            g_key, is_no_pub = group_keys[idx]

            explicit_total = it.get("total_journals_publisher")
            if explicit_total is None and pub_id_str and pub_id_str in ext_counts:
                explicit_total = ext_counts[pub_id_str]
            elif explicit_total is None and f"id:{pub_id_str}" in ext_counts:
                explicit_total = ext_counts[f"id:{pub_id_str}"]
            elif explicit_total is None and p_clean.lower() in ext_counts:
                explicit_total = ext_counts[p_clean.lower()]
            elif explicit_total is None and f"name:{p_clean.lower()}" in ext_counts:
                explicit_total = ext_counts[f"name:{p_clean.lower()}"]

            if explicit_total is not None and int(explicit_total) > 0:
                resolved_total = int(explicit_total)
            elif not is_no_pub:
                db_hist_cnt = self._lookup_historical_publisher_count(g_key, pub_id_str, sinta_pub_id, p_clean or p_raw)
                batch_cnt = pub_counts_in_batch.get(g_key, 1)
                resolved_total = max(db_hist_cnt, batch_cnt)
            else:
                resolved_total = 0

            if not is_no_pub:
                group_max_total[g_key] = max(group_max_total.get(g_key, 0), resolved_total)

            pub_name_for_subject = p_clean or p_raw
            pub_prior = self._publisher_prior(pub_name_for_subject)
            pub_texts.append(extract_publisher_lexical_signals(p_clean, p_raw, self.verified_overrides))
            subject_texts_v27.append(build_subject_text_v27(j_title, pub_name_for_subject, pub_prior))
            subject_texts_v26.append(build_subject_text(j_title, pub_name_for_subject))
            informative_journal_texts.append(extract_informative_journal_text(j_title))
            parsed_origins.append({
                "journal_id": it.get("journal_id"),
                "publisher_id": pub_id,
                "sinta_publisher_id": sinta_pub_id or None,
                "pub_key": g_key,
                "is_no_publisher": is_no_pub,
                "journal_title": j_title,
                "publisher_name_clean": p_clean,
                "publisher_name_raw": p_raw,
                "website_url": str(it.get("website_url") or ""),
                "total_journals": resolved_total,
                "sinta_subjects": parse_sinta_subjects(it.get("subject_sinta")),
                "title_groups": list(lexicon_groups(j_title)),
                "has_prior": bool(pub_prior),
            })

        for meta in parsed_origins:
            if not meta["is_no_publisher"]:
                meta["total_journals"] = group_max_total.get(meta["pub_key"], meta["total_journals"])

        total_n = len(items)
        pub_probs_list, pub_nnz_list, sinta_probs_list, sinta_nnz_list, scopus27_probs_list = [], [], [], [], []
        pub_classes: List[str] = PUBLISHER_TYPES
        sinta_classes: List[str] = SINTA_10_SUBJECTS
        scopus27_classes: List[str] = list(SCOPUS_27_TO_INDONESIAN.keys())

        for c_start in range(0, total_n, INTERNAL_CHUNK_SIZE):
            c_end = min(c_start + INTERNAL_CHUNK_SIZE, total_n)
            p_pr, pub_classes, p_nnz, _ = self._predict_proba_single_pass(
                self.pub_pipe, pub_texts[c_start:c_end], PUBLISHER_TYPES
            )
            si_pr, sinta_classes, si_nnz, _ = self._predict_proba_single_pass(
                self.sinta_pipe, subject_texts_v27[c_start:c_end], SINTA_10_SUBJECTS,
                informative_texts=informative_journal_texts[c_start:c_end],
            )
            pub_probs_list.append(p_pr); pub_nnz_list.append(p_nnz)
            sinta_probs_list.append(si_pr); sinta_nnz_list.append(si_nnz)
            if self.scopus27_pipe is not None:
                sc27_pr, scopus27_classes, _, _ = self._predict_proba_single_pass(
                    self.scopus27_pipe, subject_texts_v26[c_start:c_end], list(SCOPUS_27_TO_INDONESIAN.keys())
                )
                scopus27_probs_list.append(sc27_pr)

        pub_probs = np.vstack(pub_probs_list)
        pub_nnz = np.concatenate(pub_nnz_list)
        sinta_probs = np.vstack(sinta_probs_list)
        sinta_nnz = np.concatenate(sinta_nnz_list)
        scopus27_probs = np.vstack(scopus27_probs_list) if scopus27_probs_list else None

        # ---- Tipe penerbit: soft-voting per grup penerbit, label aturan/override per baris (sama dengan v2.6) ----
        group_prob_sums: Dict[str, np.ndarray] = {}
        group_counts: Dict[str, int] = {}
        item_rule_label: List[Optional[Tuple[str, str]]] = [None] * len(parsed_origins)
        item_default_rule: List[Optional[str]] = [None] * len(parsed_origins)
        rule_cache: Dict[Tuple[str, str, str], Tuple[Optional[Tuple[str, str]], Optional[str]]] = {}
        for idx, meta in enumerate(parsed_origins):
            if meta["is_no_publisher"]:
                continue
            gk = meta["pub_key"]
            if gk not in group_prob_sums:
                group_prob_sums[gk] = np.zeros(len(pub_classes), dtype=np.float64)
                group_counts[gk] = 0
            group_prob_sums[gk] += pub_probs[idx]
            group_counts[gk] += 1

            cache_key = (meta["publisher_name_clean"], meta["publisher_name_raw"], meta["website_url"])
            if cache_key not in rule_cache:
                c_low = re.sub(r"\s+", " ", meta["publisher_name_clean"].lower()).strip()
                r_low = re.sub(r"\s+", " ", meta["publisher_name_raw"].lower()).strip()
                ov_val = self.verified_overrides.get(c_low) or self.verified_overrides.get(r_low)
                resolved: Optional[Tuple[str, str]] = None
                default_lbl: Optional[str] = None
                if ov_val in pub_classes:
                    resolved = (ov_val, PUBLISHER_SOURCE_OVERRIDE)
                elif use_rules:
                    det_lbl, det_rsn = resolve_publisher_type_deterministic(
                        meta["publisher_name_clean"], meta["publisher_name_raw"], meta["website_url"]
                    )
                    if det_lbl in pub_classes and "Entitas Penerbit Independen" not in det_rsn:
                        src = PUBLISHER_SOURCE_OVERRIDE if det_rsn.startswith("Verified Override") else PUBLISHER_SOURCE_RULE
                        resolved = (det_lbl, src)
                    elif det_lbl in pub_classes:
                        default_lbl = det_lbl
                rule_cache[cache_key] = (resolved, default_lbl)
            item_rule_label[idx], item_default_rule[idx] = rule_cache[cache_key]

        group_mean_prob: Dict[str, np.ndarray] = {
            gk: prob_sum / max(1, group_counts[gk]) for gk, prob_sum in group_prob_sums.items()
        }

        def _resolve_publisher_for_item(idx: int) -> Tuple[str, float, float, str, str, bool]:
            mean_prob = group_mean_prob[parsed_origins[idx]["pub_key"]]
            best_i = int(np.argmax(mean_prob))
            model_cls = pub_classes[best_i]
            model_conf = float(np.round(mean_prob[best_i] * 100.0, 2))
            rule = item_rule_label[idx]
            if rule is not None:
                ov_cls, src_tag = rule
                final_conf = float(np.round(mean_prob[pub_classes.index(ov_cls)] * 100.0, 2))
                return ov_cls, final_conf, model_conf, src_tag, model_cls, bool(ov_cls != model_cls)
            return model_cls, model_conf, model_conf, PUBLISHER_SOURCE_MODEL, model_cls, False

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        thr = self.label_conf_threshold
        outputs: List[Dict[str, Any]] = []

        for idx, meta in enumerate(parsed_origins):
            notes: List[str] = []
            review_reasons: List[str] = []

            # ---------------- Subjek (model ML; selalu ada label, tanpa "Unknown") ----------------
            dec = self._subject_label_decision(sinta_probs[idx], list(sinta_classes), meta["has_prior"])
            title_has_known_words = bool(sinta_nnz[idx] > 0)
            if not title_has_known_words:
                notes.append("judul_tanpa_kata_dikenal_model")  # dulu "Unknown" (v2.6); kini tetap diklasifikasikan
            if meta["title_groups"]:
                notes.append("kamus_bidang:" + ",".join(meta["title_groups"]))

            sinta_given = meta["sinta_subjects"]
            if sinta_given:
                # Subjek SINTA asli tersedia: tampilan memakai SINTA; Scopus dibatasi ke bidang subjek SINTA itu.
                is_md = len(sinta_given) >= self.md_min_subjects
                if is_md:
                    display, display_id, display_src = MULTIDISCIPLINARY_LABEL, MULTIDISCIPLINARY_LABEL_ID, "sinta_multidisiplin"
                    pred_scopus, sc_conf = MULTIDISCIPLINARY_LABEL, None
                    pred_scopus27, sc27_conf = MULTIDISCIPLINARY_LABEL, None
                else:
                    display = ", ".join(sinta_given)
                    display_id = ", ".join(SINTA_TO_INDONESIAN.get(s, s) for s in sinta_given)
                    display_src = "sinta"
                    rumpuns = sorted({SINTA_TO_SCOPUS_MAP[s] for s in sinta_given},
                                     key=lambda r: -dec["rumpun_mass"].get(r, 0.0))
                    pred_scopus, sc_conf = rumpuns[0], None
                    allowed = sorted({f for s in sinta_given for f in SCOPUS27_ALLOWED_BY_SINTA.get(s, [])})
                    pred_scopus27, sc27_conf = self._pick_scopus27(
                        scopus27_probs[idx] if scopus27_probs is not None else None, list(scopus27_classes), allowed)
                display_conf = None
            else:
                display, display_id, display_src, display_conf = dec["label"], dec["label_id"], "ml", dec["conf"]
                pred_scopus, sc_conf = dec["rumpun"], dec["rumpun_conf"]
                if dec["level"] == LABEL_LEVEL_RUMPUN:
                    allowed = [f for f, sg in SCOPUS_27_TO_SUPERGROUP.items() if sg == dec["rumpun"]]
                    allowed += [f for s in dec["subjects"] for f in SCOPUS27_ALLOWED_BY_SINTA.get(s, [])]
                else:
                    allowed = [f for s in dec["subjects"] for f in SCOPUS27_ALLOWED_BY_SINTA.get(s, [])]
                pred_scopus27, sc27_conf = self._pick_scopus27(
                    scopus27_probs[idx] if scopus27_probs is not None else None, list(scopus27_classes), sorted(set(allowed)))
                if dec["conf"] < thr:
                    review_reasons.append("confidence_label_subjek_rendah")
            if sc27_conf is not None and sc27_conf < thr:
                notes.append("confidence_bidang_scopus27_rendah")
            pred_scopus27_id = SCOPUS_27_TO_INDONESIAN.get(pred_scopus27, pred_scopus27) if pred_scopus27 else None

            # ---------------- Tipe & ukuran penerbit (tanpa "Unknown") ----------------
            if meta["is_no_publisher"] and not ASSIGN_TYPE_WITHOUT_PUBLISHER:
                # Tidak ada penerbit yang bisa diklasifikasikan -> tipe & ukuran dikosongkan (bukan tebakan).
                pred_pub_type = None
                pub_conf = None
                pub_model_conf = None
                pub_source = PUBLISHER_SOURCE_NO_PUBLISHER
                pub_model_raw = None
                pub_conflict = False
                pub_size_en, pub_size_id = None, None
                notes.append("tanpa_nama_penerbit_tipe_tidak_diberikan")
            elif meta["is_no_publisher"]:
                pred_pub_type = self.no_name_label
                pub_conf = self.no_name_conf
                pub_model_conf = None
                pub_source = PUBLISHER_SOURCE_PRIOR_NO_NAME
                pub_model_raw = None
                pub_conflict = False
                pub_size_en, pub_size_id = classify_publisher_size_rule_based(0)
                review_reasons.append("tanpa_nama_penerbit")
            elif pub_nnz[idx] == 0 and item_rule_label[idx] is None:
                # Nama penerbit tidak memuat kata yang dikenal model & tidak ada aturan kelembagaan yang cocok:
                # pakai label aturan bawaan "penerbit independen" (COM). Keyakinan = kecocokan aturan ini
                # dengan data tipe penerbit lama SINTA pada kasus serupa (lihat evaluation report).
                pred_pub_type = item_default_rule[idx] or "COM"
                pub_conf = self.default_independent_conf
                pub_model_conf = float(np.round(np.max(pub_probs[idx]) * 100.0, 2))
                pub_source = PUBLISHER_SOURCE_DEFAULT_INDEPENDENT
                pub_model_raw = pub_classes[int(np.argmax(pub_probs[idx]))]
                pub_conflict = False
                pub_size_en, pub_size_id = classify_publisher_size_rule_based(meta["total_journals"])
                notes.append("nama_penerbit_tanpa_kata_dikenal_model")
            else:
                (pred_pub_type, pub_conf, pub_model_conf, pub_source, pub_model_raw, pub_conflict) = _resolve_publisher_for_item(idx)
                pub_size_en, pub_size_id = classify_publisher_size_rule_based(meta["total_journals"])
            if pub_conf is not None and pub_conf < self.pub_conf_threshold:
                review_reasons.append("confidence_penerbit_rendah")
            if pub_conflict:
                review_reasons.append("konflik_aturan_vs_model")

            status_str = "Needs Review" if review_reasons else "Classified"
            outputs.append({
                "journal_id": meta["journal_id"],
                "publisher_id": meta["publisher_id"],
                "sinta_publisher_id": meta["sinta_publisher_id"],
                "journal_title": meta["journal_title"],
                "publisher_name_clean": meta["publisher_name_clean"],
                "predicted_publisher_type": pred_pub_type,
                "publisher_type_source": pub_source,
                "publisher_type_model": pub_model_raw,
                "publisher_classification_confidence": pub_conf,
                "publisher_model_confidence": pub_model_conf,
                "is_rule_model_conflict": pub_conflict,
                "predicted_subject": pred_scopus,
                "predicted_subject_scopus": pred_scopus,
                "predicted_subject_scopus_27": pred_scopus27,
                "predicted_subject_scopus_27_id": pred_scopus27_id,
                "scopus_supergroup_from_27": SCOPUS_27_TO_SUPERGROUP.get(pred_scopus27) if pred_scopus27 else None,
                "is_subject_consistent": True,
                "is_low_confidence": bool(display_conf is not None and display_conf < thr),
                "scopus_confidence_score": sc_conf,
                "scopus_27_confidence_score": sc27_conf,
                "predicted_subject_sinta": dec["top1"],
                "predicted_subject_sinta_multilabel": ", ".join(dec["subjects"]),
                "sinta_confidence_score": dec["top1_conf"],
                "subject_label": dec["label"],
                "subject_label_id": dec["label_id"],
                "subject_label_level": dec["level"],
                "subject_label_confidence": dec["conf"],
                "subject_display": display,
                "subject_display_id": display_id,
                "subject_display_source": display_src,
                "subject_display_confidence": display_conf,
                "publisher_size": pub_size_en,
                "publisher_size_label_id": pub_size_id,
                "total_journals_publisher": 0 if meta["is_no_publisher"] else meta["total_journals"],
                "is_ood": not title_has_known_words,
                "processing_status": status_str,
                "review_reasons": review_reasons,
                "notes": notes,
                "model_version": self.model_version,
                "classified_at": now_str,
            })

        return outputs


def _predict_proba_with_ood(
    pipe: Dict[str, Any],
    texts: List[str],
    default_classes: Optional[List[str]] = None,
) -> Tuple[np.ndarray, List[str], np.ndarray]:
    """Fungsi kompatibilitas mundur di level modul untuk pemanggil eksternal."""
    return SClipsMLPredictor.get_instance()._predict_proba_with_ood(pipe, texts, default_classes)


class JournalPredictItem(BaseModel):
    journal_id: Optional[int] = None
    publisher_id: Optional[int] = None
    journal_title: str = Field(..., min_length=2, max_length=500)
    publisher_name_raw: Optional[str] = ""
    publisher_name_clean: Optional[str] = ""
    sinta_publisher_id: Optional[str] = ""
    website_url: Optional[str] = ""
    total_journals_publisher: Optional[int] = Field(default=None, ge=1)
    subject_sinta: Optional[str] = Field(
        default="",
        description="Opsional (v2.7): subjek SINTA asli, mis. 'Education, Science'. Bila diisi, subject_display memakai subjek SINTA.",
    )

    @field_validator("journal_title")
    @classmethod
    def validate_non_empty_title(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 2:
            raise ValueError("Judul jurnal tidak boleh kosong atau kurang dari 2 karakter.")
        return cleaned


class BatchPredictRequest(BaseModel):
    journals: List[JournalPredictItem] = Field(..., min_length=1, max_length=MAX_BATCH_SIZE)
    publisher_counts: Optional[Dict[str, int]] = Field(
        default=None,
        description="Opsional: Kamus jumlah jurnal per publisher_id atau publisher_name_clean dari SELECT COUNT(*) database.",
    )


# ==============================================================================
# PERSISTENT SQLITE TASK STORE (KOMPRESI ZLIB & PEMANGKASAN PAYLOAD LAMA)
# ==============================================================================
MAX_STORED_TASKS: int = 50
MAX_TASKS_WITH_FULL_RESULTS: int = 10
_TASK_DB_PATH: str = os.environ.get(
    "SCLIPS_TASK_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "sclips_tasks.db"),
)
_DB_INIT_LOCK = threading.Lock()
_DB_INITIALIZED = False
_DEFAULT_ON_COMPLETE_CALLBACK: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None


def register_on_complete_callback(fn: Optional[Callable[[str, List[Dict[str, Any]]], None]]) -> None:
    """
    Kompatibilitas mundur: mendaftarkan callback default jika pemanggil tidak meneruskan
    argumen `on_complete` per-task pada `enqueue_scraped_journals_for_classification`.
    """
    global _DEFAULT_ON_COMPLETE_CALLBACK
    _DEFAULT_ON_COMPLETE_CALLBACK = fn


def _encode_results_blob(results_obj: Any) -> Optional[bytes]:
    if results_obj is None:
        return None
    raw_json = json.dumps(results_obj, ensure_ascii=False).encode("utf-8")
    return b"ZLIB:" + zlib.compress(raw_json, level=6)


def _decode_results_blob(raw_val: Any) -> Any:
    if raw_val is None:
        return None
    if isinstance(raw_val, (bytes, bytearray)):
        raw_bytes = bytes(raw_val)
        if raw_bytes.startswith(b"ZLIB:"):
            raw_bytes = zlib.decompress(raw_bytes[5:])
        return json.loads(raw_bytes.decode("utf-8"))
    if isinstance(raw_val, str):
        return json.loads(raw_val)
    return None


def _ensure_task_db() -> None:
    global _DB_INITIALIZED
    if not _DB_INITIALIZED:
        with _DB_INIT_LOCK:
            if not _DB_INITIALIZED:
                with sqlite3.connect(_TASK_DB_PATH, timeout=15.0) as conn:
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("PRAGMA auto_vacuum=INCREMENTAL;")
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS ml_tasks (
                            task_id TEXT PRIMARY KEY,
                            status TEXT NOT NULL,
                            total_count INTEGER NOT NULL,
                            processed_count INTEGER NOT NULL,
                            progress_pct REAL NOT NULL,
                            created_at TEXT NOT NULL,
                            started_at TEXT,
                            finished_at TEXT,
                            model_version TEXT,
                            error TEXT,
                            results_json BLOB
                        )
                        """
                    )
                    conn.commit()
                _DB_INITIALIZED = True


def _prune_old_tasks(conn: sqlite3.Connection) -> None:
    """
    Menjaga ukuran file SQLite tetap ramping (<15 MB):
    1. Hanya menyimpan MAX_STORED_TASKS (50) baris riwayat terakhir.
    2. Hanya menyimpan array `results_json` penuh untuk MAX_TASKS_WITH_FULL_RESULTS (10) task terbaru;
       task lama tetap menyimpan metadata ringkasan namun `results_json` dikosongkan (NULL).
    """
    conn.execute(
        """
        DELETE FROM ml_tasks WHERE task_id NOT IN (
            SELECT task_id FROM ml_tasks ORDER BY rowid DESC LIMIT ?
        )
        """,
        (MAX_STORED_TASKS,),
    )
    conn.execute(
        """
        UPDATE ml_tasks SET results_json = NULL
        WHERE results_json IS NOT NULL AND task_id NOT IN (
            SELECT task_id FROM ml_tasks WHERE results_json IS NOT NULL
            ORDER BY rowid DESC LIMIT ?
        )
        """,
        (MAX_TASKS_WITH_FULL_RESULTS,),
    )


def _save_task_state(task_id: str, state: Dict[str, Any]) -> None:
    _ensure_task_db()
    results_blob = _encode_results_blob(state.get("results"))
    with sqlite3.connect(_TASK_DB_PATH, timeout=15.0) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO ml_tasks (
                task_id, status, total_count, processed_count, progress_pct,
                created_at, started_at, finished_at, model_version, error, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                state.get("status", "queued"),
                int(state.get("total_count", 0)),
                int(state.get("processed_count", 0)),
                float(state.get("progress_pct", 0.0)),
                state.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                state.get("started_at"),
                state.get("finished_at"),
                state.get("model_version"),
                state.get("error"),
                results_blob,
            ),
        )
        _prune_old_tasks(conn)
        conn.commit()


def _update_task_state(task_id: str, **updates: Any) -> None:
    _ensure_task_db()
    if not updates:
        return
    cols, vals = [], []
    for k, v in updates.items():
        if k == "results":
            cols.append("results_json = ?")
            vals.append(_encode_results_blob(v))
        else:
            cols.append(f"{k} = ?")
            vals.append(v)
    vals.append(task_id)
    with sqlite3.connect(_TASK_DB_PATH, timeout=15.0) as conn:
        conn.execute(f"UPDATE ml_tasks SET {', '.join(cols)} WHERE task_id = ?", tuple(vals))
        if "results" in updates:
            _prune_old_tasks(conn)
        conn.commit()


def _get_task_state(task_id: str, include_results: bool = True) -> Optional[Dict[str, Any]]:
    _ensure_task_db()
    with sqlite3.connect(_TASK_DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ml_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        raw_res = d.pop("results_json", None)
        if include_results:
            d["results"] = _decode_results_blob(raw_res)
        return d


def _list_task_states() -> List[Dict[str, Any]]:
    _ensure_task_db()
    with sqlite3.connect(_TASK_DB_PATH, timeout=15.0) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT task_id, status, total_count, processed_count, progress_pct, "
            "created_at, started_at, finished_at, model_version, error "
            "FROM ml_tasks ORDER BY rowid DESC LIMIT ?",
            (MAX_STORED_TASKS,),
        ).fetchall()
        return [dict(r) for r in rows]


class _SQLiteTaskStoreProxy(MutableMapping):
    """Proxy dict-like untuk kompatibilitas mundur terhadap kode/pengujian yang mengakses `_TASK_STORE`."""
    def __getitem__(self, key: str) -> Dict[str, Any]:
        st = _get_task_state(key, include_results=True)
        if st is None:
            raise KeyError(key)
        return st

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        state_copy = dict(value)
        state_copy.setdefault("task_id", key)
        _save_task_state(key, state_copy)

    def __delitem__(self, key: str) -> None:
        _ensure_task_db()
        with sqlite3.connect(_TASK_DB_PATH, timeout=15.0) as conn:
            cur = conn.execute("DELETE FROM ml_tasks WHERE task_id = ?", (key,))
            conn.commit()
            if cur.rowcount == 0:
                raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        for item in _list_task_states():
            yield item["task_id"]

    def __len__(self) -> int:
        return len(_list_task_states())


_TASK_STORE: MutableMapping = _SQLiteTaskStoreProxy()


def _execute_prediction_in_background(
    task_id: str,
    raw_list: List[Dict[str, Any]],
    publisher_counts: Optional[Dict[str, int]] = None,
    on_complete: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None,
) -> None:
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _update_task_state(
        task_id,
        status="running",
        started_at=started_at,
        progress_pct=10.0,
    )
    try:
        predictor = SClipsMLPredictor.get_instance()
        all_results = predictor.predict_batch(raw_list, publisher_counts_override=publisher_counts)

        cb = on_complete or _DEFAULT_ON_COMPLETE_CALLBACK
        if cb is not None:
            try:
                cb(task_id, all_results)
            except Exception:
                logger.exception("Gagal menjalankan callback database untuk task %s", task_id)

        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _update_task_state(
            task_id,
            status="completed",
            model_version=predictor.model_version,
            processed_count=len(all_results),
            progress_pct=100.0,
            finished_at=finished_at,
            results=all_results,
        )
        logger.info("Background task %s selesai memproses %d jurnal.", task_id, len(all_results))
    except Exception as exc:
        logger.exception("Background task %s gagal.", task_id)
        _update_task_state(
            task_id,
            status="failed",
            error=str(exc),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


router = APIRouter(prefix="/classify", tags=["Classification"])


def preload_model_on_startup(model_path: Optional[str] = None) -> SClipsMLPredictor:
    """Preload model ke RAM saat aplikasi FastAPI startup agar request pertama bebas latensi."""
    _ensure_task_db()
    return SClipsMLPredictor.get_instance(model_path=model_path)


@router.post("/predict")
async def predict_journals_endpoint(
    payload: BatchPredictRequest,
    background_tasks: BackgroundTasks,
    background: bool = Query(
        default=False,
        description="Set background=true agar prediksi dijalankan di BackgroundTasks tanpa membuat request menunggu.",
    ),
) -> Any:
    try:
        raw_list = [
            item.model_dump() if hasattr(item, "model_dump") else item.dict()
            for item in payload.journals
        ]

        if background or len(raw_list) > INTERNAL_CHUNK_SIZE:
            task_id = f"ml_task_{uuid.uuid4().hex[:12]}"
            _save_task_state(
                task_id,
                {
                    "task_id": task_id,
                    "status": "queued",
                    "total_count": len(raw_list),
                    "processed_count": 0,
                    "progress_pct": 0.0,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "started_at": None,
                    "finished_at": None,
                    "model_version": None,
                    "error": None,
                    "results": None,
                },
            )
            background_tasks.add_task(
                _execute_prediction_in_background, task_id, raw_list, payload.publisher_counts, None
            )
            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "mode": "background",
                    "task_id": task_id,
                    "total_count": len(raw_list),
                    "status_check_url": f"/classify/tasks/{task_id}",
                    "message": "Prediksi ML sedang diproses di background task agar server tidak lag.",
                },
            )

        predictor = await asyncio.to_thread(SClipsMLPredictor.get_instance)
        results = await asyncio.to_thread(
            predictor.predict_batch, raw_list, payload.publisher_counts
        )
        return {
            "status": "success",
            "mode": "sync_non_blocking",
            "model_version": predictor.model_version,
            "count": len(results),
            "results": results,
        }
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception:
        logger.exception("Gagal memproses permintaan prediksi batch pada modul ML.")
        raise HTTPException(
            status_code=500,
            detail="Terjadi kesalahan internal pada server saat menjalankan klasifikasi.",
        )


@router.post("/predict-async", status_code=202)
async def predict_journals_async_endpoint(
    payload: BatchPredictRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """Endpoint khusus BackgroundTask: langsung merespons dalam <5ms dan memproses ribuan jurnal di belakang layar."""
    raw_list = [
        item.model_dump() if hasattr(item, "model_dump") else item.dict()
        for item in payload.journals
    ]
    task_id = f"ml_task_{uuid.uuid4().hex[:12]}"
    _save_task_state(
        task_id,
        {
            "task_id": task_id,
            "status": "queued",
            "total_count": len(raw_list),
            "processed_count": 0,
            "progress_pct": 0.0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "started_at": None,
            "finished_at": None,
            "model_version": None,
            "error": None,
            "results": None,
        },
    )
    background_tasks.add_task(
        _execute_prediction_in_background, task_id, raw_list, payload.publisher_counts, None
    )
    return {
        "status": "accepted",
        "mode": "background",
        "task_id": task_id,
        "total_count": len(raw_list),
        "status_check_url": f"/classify/tasks/{task_id}",
        "message": "Prediksi ML dijadwalkan di BackgroundTasks.",
    }


@router.get("/tasks/{task_id}")
async def get_prediction_task_status(
    task_id: str,
    include_results: bool = Query(
        default=True,
        description="Set false jika hanya ingin mengecek persentase progres tanpa mengambil array results.",
    ),
) -> Dict[str, Any]:
    """Mengecek progres & mengambil hasil BackgroundTask dari SQLite task store berdasarkan task_id."""
    task = await asyncio.to_thread(_get_task_state, task_id, include_results)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task ID '{task_id}' tidak ditemukan.")
    return task


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Status model yang sedang aktif. Worker/fullstack bisa mencocokkan `model_sha256` dengan README rilis
    sebelum mengirim batch. Memanggil endpoint ini juga memuat model bila belum dimuat.
    """
    try:
        p = await asyncio.to_thread(SClipsMLPredictor.get_instance)
    except Exception as exc:
        logger.exception("Health check: model gagal dimuat.")
        raise HTTPException(status_code=503, detail=f"Model belum siap: {type(exc).__name__}")
    return {
        "status": "ok",
        "model_version": p.model_version,
        "model_sha256": p.model_sha256,
        "trained_sklearn_version": p.trained_sklearn_version,
        "runtime_sklearn_version": p.runtime_sklearn_version,
        "sklearn_version_match": p.trained_sklearn_version.split(".")[:2] == p.runtime_sklearn_version.split(".")[:2],
        "sync_batch_limit": INTERNAL_CHUNK_SIZE,
        "max_batch_size": MAX_BATCH_SIZE,
        "thresholds_pct": {
            "subject_label": p.label_conf_threshold,
            "publisher_type": p.pub_conf_threshold,
        },
        "multidisciplinary_min_sinta_subjects": p.md_min_subjects,
        "classes": {
            "publisher_type": p._pipe_classes(p.pub_pipe),
            "subject_scopus_4": list(SCOPUS_4_CLUSTERS) + [MULTIDISCIPLINARY_LABEL],
            "subject_sinta_10": p._pipe_classes(p.sinta_pipe),
            "subject_scopus_27": p._pipe_classes(p.scopus27_pipe),
        },
    }


@router.get("/tasks")
async def list_prediction_tasks() -> Dict[str, Any]:
    """Menampilkan daftar riwayat BackgroundTask terakhir dari SQLite task store."""
    summaries = await asyncio.to_thread(_list_task_states)
    return {"count": len(summaries), "tasks": summaries}


def enqueue_scraped_journals_for_classification(
    background_tasks: BackgroundTasks,
    scraped_items: List[Dict[str, Any]],
    on_complete: Optional[Callable[[str, List[Dict[str, Any]]], None]] = None,
    publisher_counts: Optional[Dict[str, int]] = None,
) -> str:
    """
    Fungsi helper untuk dipanggil langsung oleh modul Scraper / Sinkronisasi Admin:
    Begitu scraper Data Mining selesai mengambil jurnal baru dari SINTA, panggil fungsi ini
    agar klasifikasi ML berjalan otomatis di background dan langsung meng-update database.
    """
    task_id = f"ml_sync_{uuid.uuid4().hex[:12]}"
    _save_task_state(
        task_id,
        {
            "task_id": task_id,
            "status": "queued",
            "total_count": len(scraped_items),
            "processed_count": 0,
            "progress_pct": 0.0,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "started_at": None,
            "finished_at": None,
            "model_version": None,
            "error": None,
            "results": None,
        },
    )
    background_tasks.add_task(
        _execute_prediction_in_background, task_id, scraped_items, publisher_counts, on_complete
    )
    return task_id


async def classify_scraped_journals_async(
    scraped_items: List[Dict[str, Any]],
    publisher_counts: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    """
    Fungsi async non-blocking (asyncio.to_thread) yang menghitung penerbit secara utuh untuk seluruh batch
    tanpa memecah hitungan penerbit di batas chunk.
    """
    predictor = await asyncio.to_thread(SClipsMLPredictor.get_instance)
    return await asyncio.to_thread(predictor.predict_batch, scraped_items, publisher_counts)
