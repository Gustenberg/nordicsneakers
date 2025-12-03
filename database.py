"""
Database modul til SQLite operationer
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional
import json

from config import DATABASE_PATH, setup_logging

logger = setup_logging("database")


def get_connection() -> sqlite3.Connection:
    """Hent en database forbindelse med row factory."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    """Initialiser databasen med nødvendige tabeller."""
    conn = get_connection()
    cursor = conn.cursor()

    # WTB Listings tabel - hvad andre butikker søger efter
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wtb_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            name TEXT NOT NULL,
            brand TEXT,
            size TEXT,
            price_min REAL,
            price_max REAL,
            store_name TEXT,
            store_count INTEGER DEFAULT 1,
            image_url TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tilføj image_url kolonne hvis den mangler (migration)
    try:
        cursor.execute("ALTER TABLE wtb_listings ADD COLUMN image_url TEXT")
        logger.debug("Tilføjet image_url kolonne til wtb_listings")
    except sqlite3.OperationalError:
        pass  # Kolonne eksisterer allerede

    # Mine Produkter tabel - din butiks lager
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS my_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE,
            name TEXT NOT NULL,
            brand TEXT,
            sizes TEXT,
            price REAL,
            url TEXT,
            image_url TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Tilføj image_url kolonne hvis den mangler (migration)
    try:
        cursor.execute("ALTER TABLE my_products ADD COLUMN image_url TEXT")
        logger.debug("Tilføjet image_url kolonne til my_products")
    except sqlite3.OperationalError:
        pass  # Kolonne eksisterer allerede

    # Opret indekser for hurtigere opslag
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wtb_sku ON wtb_listings(sku)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wtb_name ON wtb_listings(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_my_sku ON my_products(sku)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_my_name ON my_products(name)")

    # Unikt indeks for WTB deduplikering (SKU + butik, eller navn + butik hvis SKU er NULL)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wtb_sku_store
        ON wtb_listings(COALESCE(sku, name), store_name)
    """)

    conn.commit()
    conn.close()
    logger.debug("Database initialiseret")


# WTB Listings operationer
def insert_wtb_listing(name: str, sku: Optional[str] = None, brand: Optional[str] = None,
                       size: Optional[str] = None, price_min: Optional[float] = None,
                       price_max: Optional[float] = None, store_name: Optional[str] = None,
                       image_url: Optional[str] = None):
    """Indsæt et nyt WTB opslag, spring over hvis det allerede eksisterer."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO wtb_listings (sku, name, brand, size, price_min, price_max, store_name, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(COALESCE(sku, name), store_name) DO NOTHING
    """, (sku, name, brand, size, price_min, price_max, store_name, image_url))
    conn.commit()
    conn.close()


def clear_wtb_listings():
    """Ryd alle WTB opslag (før ny scrape)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM wtb_listings")
    conn.commit()
    conn.close()
    logger.info("WTB opslag ryddet")


def get_all_wtb_listings() -> list[dict]:
    """Hent alle WTB opslag."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sku, name, brand, size, price_min, price_max, store_name,
               store_count, image_url, last_seen, created_at
        FROM wtb_listings
        ORDER BY name
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_wtb_demand_summary() -> list[dict]:
    """Hent WTB opslag grupperet efter SKU/navn med efterspørgsels antal."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COALESCE(sku, name) as identifier,
            name,
            sku,
            brand,
            COUNT(*) as demand_count,
            GROUP_CONCAT(DISTINCT store_name) as stores,
            MIN(price_min) as min_price,
            MAX(price_max) as max_price,
            GROUP_CONCAT(DISTINCT size) as sizes,
            MAX(image_url) as image_url
        FROM wtb_listings
        GROUP BY COALESCE(sku, name)
        ORDER BY demand_count DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# Mine Produkter operationer
def insert_my_product(name: str, sku: Optional[str] = None, brand: Optional[str] = None,
                      sizes: Optional[list] = None, price: Optional[float] = None,
                      url: Optional[str] = None, image_url: Optional[str] = None):
    """Indsæt et produkt, spring over hvis SKU allerede eksisterer."""
    conn = get_connection()
    cursor = conn.cursor()
    sizes_json = json.dumps(sizes) if sizes else None

    cursor.execute("""
        INSERT INTO my_products (sku, name, brand, sizes, price, url, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sku) DO NOTHING
    """, (sku, name, brand, sizes_json, price, url, image_url))
    conn.commit()
    conn.close()


def clear_my_products():
    """Ryd alle mine produkter (før ny scrape)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM my_products")
    conn.commit()
    conn.close()
    logger.info("Mine produkter ryddet")


def get_all_my_products() -> list[dict]:
    """Hent alle produkter fra min butik."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, sku, name, brand, sizes, price, url, image_url, last_updated
        FROM my_products
        ORDER BY name
    """)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        if d['sizes']:
            d['sizes'] = json.loads(d['sizes'])
        results.append(d)
    return results


def get_wtb_count() -> int:
    """Hent antal WTB opslag."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM wtb_listings")
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_my_products_count() -> int:
    """Hent antal af mine produkter."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM my_products")
    count = cursor.fetchone()[0]
    conn.close()
    return count


# Initialiser database ved import
init_database()
