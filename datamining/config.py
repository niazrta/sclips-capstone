import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL = os.getenv("DATABASE_URL")
    SINTA_BASE_URL = os.getenv(
        "SINTA_BASE_URL",
        "https://sinta.kemdiktisaintek.go.id"
    )
    SCRAPE_DELAY_SECONDS = float(os.getenv("SCRAPE_DELAY_SECONDS", 2))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


config = Config()