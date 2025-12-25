"""
Butik Scraper
Scraper dit eget butiks produktkatalog for at sammenligne med WTB efterspørgsel.
Understøtter Shopify, WooCommerce og CSV import.
Bruger httpx og BeautifulSoup til HTTP scraping.
"""
import asyncio
import csv
import json
import re
from pathlib import Path
from typing import Optional
import httpx
from bs4 import BeautifulSoup

from config import MY_STORE_URL, MY_STORE_TYPE, REQUEST_DELAY, setup_logging
import database

logger = setup_logging("store_scraper")


class StoreScraper:
    """Scraper til dit butiks produktkatalog."""

    def __init__(self, store_url: str = None, store_type: str = None):
        self.store_url = store_url or MY_STORE_URL
        self.store_type = store_type or MY_STORE_TYPE
        self.items_scraped = 0
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }

    async def scrape_products(self, progress_callback=None) -> list[dict]:
        """
        Scrape produkter fra din butik.
        Registrerer automatisk butikstype og bruger passende metode.
        """
        # Nordic Sneakers bruger sin egen API URL, behøver ikke store_url
        if self.store_type == "nordic_sneakers":
            return await self._scrape_nordic_sneakers(progress_callback)

        if not self.store_url:
            logger.warning("Ingen butiks URL konfigureret")
            if progress_callback:
                progress_callback("Ingen butiks URL konfigureret. Indstil MY_STORE_URL i config.py eller importer via CSV")
            return []

        if self.store_type == "shopify":
            return await self._scrape_shopify(progress_callback)
        elif self.store_type == "woocommerce":
            return await self._scrape_woocommerce(progress_callback)
        else:
            return await self._scrape_generic(progress_callback)

    async def _scrape_shopify(self, progress_callback=None) -> list[dict]:
        """Scrape produkter fra en Shopify butik via products.json endpoint."""
        items = []

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0) as client:
            try:
                page_num = 1
                while True:
                    url = f"{self.store_url.rstrip('/')}/products.json?page={page_num}&limit=250"

                    if progress_callback:
                        progress_callback(f"Henter Shopify produkter side {page_num}")

                    response = await client.get(url)

                    if response.status_code != 200:
                        break

                    try:
                        data = response.json()
                        products = data.get('products', [])

                        if not products:
                            break

                        for product in products:
                            item = self._parse_shopify_product(product)
                            if item:
                                items.append(item)

                        page_num += 1
                        await asyncio.sleep(REQUEST_DELAY)

                    except json.JSONDecodeError:
                        break

            except Exception as e:
                logger.error(f"Fejl ved Shopify scraping: {e}")
                if progress_callback:
                    progress_callback(f"Fejl ved Shopify scraping: {e}")

        self.items_scraped = len(items)
        logger.info(f"Shopify scrape færdig: {len(items)} produkter")
        return items

    def _parse_shopify_product(self, product: dict) -> Optional[dict]:
        """Parse et Shopify produkt JSON objekt."""
        try:
            sizes = []
            prices = []
            for variant in product.get('variants', []):
                if variant.get('available', True):
                    size = variant.get('option1') or variant.get('title')
                    if size and size != 'Default Title':
                        sizes.append(size)
                    price = variant.get('price')
                    if price:
                        prices.append(float(price))

            # Udtræk billede URL fra featured_image eller images array
            image_url = None
            if product.get('featured_image'):
                image_url = product['featured_image'].get('src') if isinstance(product['featured_image'], dict) else product['featured_image']
            elif product.get('images') and len(product['images']) > 0:
                first_image = product['images'][0]
                image_url = first_image.get('src') if isinstance(first_image, dict) else first_image

            return {
                "name": product.get('title', ''),
                "sku": product.get('variants', [{}])[0].get('sku') if product.get('variants') else None,
                "brand": product.get('vendor', ''),
                "sizes": sizes if sizes else None,
                "price": min(prices) if prices else None,
                "url": f"{self.store_url}/products/{product.get('handle', '')}",
                "image_url": image_url
            }
        except Exception:
            return None

    async def _scrape_woocommerce(self, progress_callback=None) -> list[dict]:
        """Scrape produkter fra en WooCommerce butik."""
        items = []

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0) as client:
            try:
                page_num = 1
                while True:
                    url = f"{self.store_url.rstrip('/')}/shop/page/{page_num}/"

                    if progress_callback:
                        progress_callback(f"Henter WooCommerce side {page_num}")

                    response = await client.get(url)

                    if response.status_code == 404:
                        break

                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'lxml')
                        products = soup.select('.product, .type-product')

                        if not products:
                            break

                        for prod_elem in products:
                            item = self._parse_woocommerce_product(prod_elem)
                            if item:
                                items.append(item)

                    page_num += 1
                    await asyncio.sleep(REQUEST_DELAY)

            except Exception as e:
                logger.error(f"Fejl ved WooCommerce scraping: {e}")
                if progress_callback:
                    progress_callback(f"Fejl ved WooCommerce scraping: {e}")

        self.items_scraped = len(items)
        logger.info(f"WooCommerce scrape færdig: {len(items)} produkter")
        return items

    def _parse_woocommerce_product(self, element) -> Optional[dict]:
        """Parse et WooCommerce produkt element."""
        try:
            title_elem = element.select_one('.woocommerce-loop-product__title, .product-title, h2, h3')
            link_elem = element.select_one('a[href*="/product/"]')
            price_elem = element.select_one('.price, .amount')
            img_elem = element.select_one('img.attachment-woocommerce_thumbnail, .woocommerce-loop-product__thumbnail img, img')

            name = title_elem.get_text(strip=True) if title_elem else ""
            url = link_elem.get('href', '') if link_elem else ""
            price_text = price_elem.get_text(strip=True) if price_elem else ""

            price = None
            price_match = re.search(r'[\d.,]+', price_text.replace(',', ''))
            if price_match:
                price = float(price_match.group())

            # Udtræk billede URL
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src') or img_elem.get('data-lazy-src')

            return {
                "name": name,
                "sku": None,
                "brand": None,
                "sizes": None,
                "price": price,
                "url": url,
                "image_url": image_url
            }
        except Exception:
            return None

    async def _scrape_generic(self, progress_callback=None) -> list[dict]:
        """Generisk scraper til ukendte butikstyper."""
        items = []

        async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0) as client:
            try:
                if progress_callback:
                    progress_callback(f"Scraper {self.store_url}")

                response = await client.get(self.store_url)

                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'lxml')

                    selectors = [
                        '.product', '.product-card', '.product-item',
                        '[class*="product"]', 'article',
                        '.item', '.card'
                    ]

                    for selector in selectors:
                        elements = soup.select(selector)
                        if len(elements) > 2:
                            for elem in elements:
                                item = self._parse_generic_product(elem)
                                if item:
                                    items.append(item)
                            break

            except Exception as e:
                logger.error(f"Fejl ved generisk scraping: {e}")
                if progress_callback:
                    progress_callback(f"Fejl ved scraping af butik: {e}")

        self.items_scraped = len(items)
        return items

    def _parse_generic_product(self, element) -> Optional[dict]:
        """Parse et generisk produkt element."""
        try:
            text = element.get_text(separator=' ', strip=True)
            if not text or len(text) < 5:
                return None

            link = element.select_one('a')
            url = link.get('href') if link else None

            heading = element.select_one('h1, h2, h3, h4, h5')
            name = heading.get_text(strip=True) if heading else text.split()[0] if text else ""

            price = None
            price_match = re.search(r'[€$£]\s*(\d+(?:[.,]\d{2})?)', text)
            if price_match:
                price = float(price_match.group(1).replace(',', '.'))

            sku = None
            sku_match = re.search(r'\b([A-Z]{2,}\d{4,}[\w-]*)\b', text, re.IGNORECASE)
            if sku_match:
                sku = sku_match.group(1).upper()

            # Udtræk billede URL
            img_elem = element.select_one('img')
            image_url = None
            if img_elem:
                image_url = img_elem.get('src') or img_elem.get('data-src') or img_elem.get('data-lazy-src')

            return {
                "name": name[:100],
                "sku": sku,
                "brand": None,
                "sizes": None,
                "price": price,
                "url": url,
                "image_url": image_url
            }
        except Exception:
            return None

    async def _scrape_nordic_sneakers(self, progress_callback=None) -> list[dict]:
        """Scrape produkter fra Nordic Sneakers sælger API med pagination."""
        from config import NORDIC_SNEAKERS_API_URL, NORDIC_SNEAKERS_COOKIE

        items = []
        seen_ids = set()  # Track seen product IDs to detect duplicates

        if not NORDIC_SNEAKERS_COOKIE:
            logger.warning("Ingen Nordic Sneakers cookie konfigureret")
            if progress_callback:
                progress_callback("Ingen Nordic Sneakers cookie konfigureret. Indstil NORDIC_SNEAKERS_COOKIE i .env")
            return []

        # Cookie er en Flask session cookie, skal hedde 'session'
        cookie_value = NORDIC_SNEAKERS_COOKIE
        if not cookie_value.startswith("session="):
            cookie_value = f"session={cookie_value}"

        headers = {
            **self.headers,
            "Cookie": cookie_value
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=60.0) as client:
            try:
                page = 1
                max_pages = 100  # Safety limit

                while page <= max_pages:
                    if progress_callback:
                        progress_callback(f"Henter Nordic Sneakers produkter (side {page}, {len(items)} fundet)...")

                    response = await client.get(f"{NORDIC_SNEAKERS_API_URL}?page={page}")

                    if response.status_code == 200:
                        data = response.json()

                        # Get products from response
                        products = []
                        if isinstance(data, dict):
                            products = data.get('data', data.get('products', data.get('items', [])))
                        elif isinstance(data, list):
                            products = data

                        if not products:
                            logger.debug(f"No products on page {page}, stopping")
                            break

                        # Check for duplicates to detect if API is repeating
                        new_products_count = 0
                        for product in products:
                            # Use SKU or name as unique identifier
                            product_id = product.get('id') or product.get('sku') or product.get('name', '')

                            if product_id and product_id in seen_ids:
                                continue  # Skip duplicate

                            if product_id:
                                seen_ids.add(product_id)

                            item = self._parse_nordic_product(product)
                            if item:
                                items.append(item)
                                new_products_count += 1

                        logger.debug(f"Side {page}: {len(products)} produkter, {new_products_count} nye")

                        # If no new products were added, we're getting duplicates - stop
                        if new_products_count == 0:
                            logger.debug(f"No new products on page {page}, stopping (duplicates detected)")
                            break

                        page += 1
                        await asyncio.sleep(0.5)  # Small delay between requests

                    elif response.status_code == 401:
                        logger.warning("Nordic Sneakers godkendelse fejlede - cookie kan være udløbet")
                        if progress_callback:
                            progress_callback("Nordic Sneakers godkendelse fejlede. Cookie kan være udløbet.")
                        break
                    else:
                        logger.error(f"Nordic Sneakers API fejl: {response.status_code}")
                        if progress_callback:
                            progress_callback(f"Nordic Sneakers API fejl: {response.status_code}")
                        break

                logger.info(f"Nordic Sneakers scrape færdig: {len(items)} produkter ({page-1} sider)")
                if progress_callback:
                    progress_callback(f"Fandt {len(items)} Nordic Sneakers produkter")

            except Exception as e:
                logger.error(f"Fejl ved Nordic Sneakers scraping: {e}")
                if progress_callback:
                    progress_callback(f"Fejl ved Nordic Sneakers scraping: {e}")

        self.items_scraped = len(items)
        return items

    def _parse_nordic_product(self, product: dict) -> Optional[dict]:
        """Parse et Nordic Sneakers API produkt."""
        try:
            name = product.get('name', '')
            # Udtræk brand fra første ord i navnet (f.eks. "Adidas AdiFom..." -> "Adidas")
            brand = name.split()[0] if name else None

            # Udtræk størrelse nøgler fra sizes objekt
            sizes_obj = product.get('sizes', {})
            sizes = list(sizes_obj.keys()) if sizes_obj else None

            # Konstruer produkt URL fra slug
            slug = product.get('slug', '')
            url = f"https://nordicsneakers.dk/products/{slug}" if slug else None

            # Prøv at hente billede URL fra forskellige mulige feltnavne
            image_url = (
                product.get('image_url') or
                product.get('image') or
                product.get('featured_image') or
                product.get('thumbnail') or
                product.get('picture') or
                None
            )
            # Hvis images er et array, tag det første
            if not image_url and product.get('images'):
                images = product.get('images')
                if isinstance(images, list) and len(images) > 0:
                    first_img = images[0]
                    image_url = first_img.get('src') if isinstance(first_img, dict) else first_img

            return {
                "name": name,
                "sku": product.get('sku'),
                "brand": brand,
                "sizes": sizes,
                "price": None,  # Ikke tilgængelig fra API
                "url": url,
                "image_url": image_url
            }
        except Exception:
            return None

    def import_from_csv(self, csv_path: str, progress_callback=None) -> list[dict]:
        """
        Importer produkter fra en CSV fil.
        Forventede kolonner: name, sku, brand, sizes, price, url, image_url
        """
        items = []
        path = Path(csv_path)

        if not path.exists():
            logger.warning(f"CSV fil ikke fundet: {csv_path}")
            if progress_callback:
                progress_callback(f"CSV fil ikke fundet: {csv_path}")
            return items

        try:
            with open(path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    item = {
                        "name": row.get('name', '').strip(),
                        "sku": row.get('sku', '').strip() or None,
                        "brand": row.get('brand', '').strip() or None,
                        "sizes": row.get('sizes', '').split(',') if row.get('sizes') else None,
                        "price": float(row['price']) if row.get('price') else None,
                        "url": row.get('url', '').strip() or None,
                        "image_url": row.get('image_url', '').strip() or None
                    }

                    if item["name"]:
                        items.append(item)

            logger.info(f"Importerede {len(items)} produkter fra CSV")
            if progress_callback:
                progress_callback(f"Importerede {len(items)} produkter fra CSV")

        except Exception as e:
            logger.error(f"Fejl ved læsning af CSV: {e}")
            if progress_callback:
                progress_callback(f"Fejl ved læsning af CSV: {e}")

        self.items_scraped = len(items)
        return items

    def save_to_database(self, items: list[dict]):
        """
        Gem scrapede produkter til databasen med session tracking.
        Hvert scrape opretter en ny session og bevarer historisk data.
        """
        if not items:
            logger.info("Ingen produkter at gemme")
            return None

        # Opret ny scrape session
        session_id = database.create_scrape_session(
            scrape_type='products',
            store_name=self.store_type
        )

        # Brug batch insert for bedre performance
        database.insert_my_products_batch(items, session_id)

        # Marker session som færdig
        database.complete_scrape_session(session_id, len(items))

        logger.info(f"Gemte {len(items)} produkter til database (session: {session_id})")
        return session_id


async def main():
    """Test scraperen."""
    scraper = StoreScraper()

    def progress(msg):
        logger.info(msg)

    logger.info(f"Butik URL: {scraper.store_url or 'Ikke konfigureret'}")
    logger.info(f"Butik Type: {scraper.store_type}")

    if scraper.store_url or scraper.store_type == "nordic_sneakers":
        items = await scraper.scrape_products(progress_callback=progress)
        logger.info(f"Fandt {len(items)} produkter")
        for item in items[:5]:
            logger.info(f"  - {item['name']} (SKU: {item.get('sku', 'N/A')})")


if __name__ == "__main__":
    asyncio.run(main())
