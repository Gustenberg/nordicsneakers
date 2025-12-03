"""
WTB Market List Scraper
Kalder Node.js Playwright scraperen for at omgå bot beskyttelse.
Understøtter flere butikker fra stores.json konfiguration.
"""
import asyncio
import json
import subprocess
from pathlib import Path

from config import BASE_DIR, setup_logging
import database

logger = setup_logging("wtb_scraper")
STORES_FILE = BASE_DIR / "stores.json"


class WTBScraper:
    """Scraper til wtbmarketlist.eu ved brug af Node.js Playwright"""

    def __init__(self):
        self.script_path = BASE_DIR / "scraper.js"
        self.items_scraped = 0

    def _load_stores(self) -> list[dict]:
        """Indlæs aktiverede butikker fra konfiguration."""
        if STORES_FILE.exists():
            with open(STORES_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return [s for s in config.get("stores", []) if s.get("enabled", True)]
        return []

    async def scrape_store(self, store_url: str, progress_callback=None) -> list[dict]:
        """
        Scrape WTB opslag fra en specifik butik.
        Bruger Node.js Playwright til at omgå Vercel sikkerhed.
        """
        items = []

        if progress_callback:
            progress_callback(f"Scraper {store_url}")

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["node", str(self.script_path), store_url],
                    capture_output=True,
                    text=True,
                    cwd=str(BASE_DIR),
                    timeout=120
                )
            )

            if result.stdout:
                try:
                    items = json.loads(result.stdout)
                except json.JSONDecodeError:
                    logger.warning("Kunne ikke parse scraper output")
                    if progress_callback:
                        progress_callback("Fejl ved parsing af scraper output")

            if result.stderr and progress_callback:
                for line in result.stderr.split('\n'):
                    if line.strip() and '[Progress]' in line:
                        progress_callback(line.strip())

        except subprocess.TimeoutExpired:
            logger.warning("Scrape timeout efter 120 sekunder")
            if progress_callback:
                progress_callback("Scrape timeout efter 120 sekunder")
        except Exception as e:
            logger.error(f"Scrape fejl: {e}")
            if progress_callback:
                progress_callback(f"Fejl: {str(e)}")

        return items

    async def scrape_all_stores(self, progress_callback=None) -> list[dict]:
        """
        Scrape alle aktiverede butikker fra stores.json.
        Bruger --all flag så Node.js håndterer flere butikker effektivt.
        """
        items = []

        if progress_callback:
            progress_callback("Starter multi-butik scrape...")

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    ["node", str(self.script_path), "--all"],
                    capture_output=True,
                    text=True,
                    cwd=str(BASE_DIR),
                    timeout=600  # 10 minutter for flere butikker
                )
            )

            if result.stdout:
                try:
                    items = json.loads(result.stdout)
                    logger.info(f"Fandt {len(items)} sneakers totalt")
                    if progress_callback:
                        progress_callback(f"Fandt {len(items)} sneakers totalt")
                except json.JSONDecodeError:
                    logger.warning("Kunne ikke parse scraper output")
                    if progress_callback:
                        progress_callback("Fejl ved parsing af scraper output")

            if result.stderr and progress_callback:
                for line in result.stderr.split('\n'):
                    if line.strip():
                        progress_callback(line.strip())

        except subprocess.TimeoutExpired:
            logger.warning("Scrape timeout efter 10 minutter")
            if progress_callback:
                progress_callback("Scrape timeout efter 10 minutter")
        except Exception as e:
            logger.error(f"Scrape fejl: {e}")
            if progress_callback:
                progress_callback(f"Fejl: {str(e)}")

        self.items_scraped = len(items)
        return items

    async def scrape_main_wtb_list(self, progress_callback=None) -> list[dict]:
        """
        Scrape alle aktiverede butikker (bagudkompatibelt metodenavn).
        """
        return await self.scrape_all_stores(progress_callback)

    def save_to_database(self, items: list[dict], clear_existing: bool = False):
        """Gem scrapede elementer til databasen. Tilføjer kun nye elementer som standard."""
        if clear_existing:
            database.clear_wtb_listings()

        for item in items:
            database.insert_wtb_listing(
                name=item.get("name", ""),
                sku=item.get("sku"),
                brand=item.get("brand"),
                size=item.get("size"),
                price_min=item.get("price_min"),
                price_max=item.get("price_max"),
                store_name=item.get("store_name"),
                image_url=item.get("image_url")
            )

        logger.info(f"Gemte {len(items)} WTB opslag til database")


async def main():
    """Test scraperen."""
    scraper = WTBScraper()

    def progress(msg):
        logger.info(msg)

    logger.info("Starter WTB scrape af alle butikker...")
    items = await scraper.scrape_all_stores(progress_callback=progress)
    logger.info(f"Fandt {len(items)} elementer totalt")

    # Grupper efter butik
    stores = {}
    for item in items:
        store = item.get("store_name", "ukendt")
        stores[store] = stores.get(store, 0) + 1

    logger.info("Elementer per butik:")
    for store, count in stores.items():
        logger.info(f"  - {store}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
