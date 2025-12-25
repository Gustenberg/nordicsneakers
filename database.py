"""
Database module for MySQL operations with scrape session tracking
"""
import mysql.connector
from mysql.connector import pooling
from datetime import datetime
from typing import Optional
import json
import uuid

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, setup_logging

logger = setup_logging("database")

# Connection pool for better performance
connection_pool = None


def get_pool():
    """Get or create the connection pool."""
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = pooling.MySQLConnectionPool(
                pool_name="wtb_pool",
                pool_size=5,
                pool_reset_session=True,
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASSWORD,
                database=DB_NAME,
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci',
                autocommit=False
            )
            logger.info(f"MySQL connection pool created for {DB_HOST}:{DB_PORT}/{DB_NAME}")
        except mysql.connector.Error as err:
            logger.error(f"Failed to create connection pool: {err}")
            raise
    return connection_pool


def get_connection():
    """Get a database connection from the pool."""
    return get_pool().get_connection()


def init_database():
    """Initialize the database with required tables."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Scrape sessions table - tracks all scrapes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scrape_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(50) UNIQUE NOT NULL,
                scrape_type ENUM('wtb', 'products') NOT NULL,
                store_name VARCHAR(255),
                items_count INT DEFAULT 0,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP NULL,
                INDEX idx_session_type (scrape_type),
                INDEX idx_session_store (store_name),
                INDEX idx_session_started (started_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # WTB Listings table - what other stores are looking for
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wtb_listings (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sku VARCHAR(255),
                name VARCHAR(500) NOT NULL,
                brand VARCHAR(255),
                size VARCHAR(255),
                price_min DECIMAL(10,2),
                price_max DECIMAL(10,2),
                store_name VARCHAR(255),
                store_count INT DEFAULT 1,
                image_url TEXT,
                scrape_session VARCHAR(50) NOT NULL,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_wtb_sku (sku),
                INDEX idx_wtb_name (name(100)),
                INDEX idx_wtb_session (scrape_session),
                INDEX idx_wtb_store (store_name),
                INDEX idx_wtb_last_seen (last_seen),
                FOREIGN KEY (scrape_session) REFERENCES scrape_sessions(session_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # My Products table - your store's inventory
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS my_products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sku VARCHAR(255),
                name VARCHAR(500) NOT NULL,
                brand VARCHAR(255),
                sizes TEXT,
                price DECIMAL(10,2),
                url TEXT,
                image_url TEXT,
                scrape_session VARCHAR(50) NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_my_sku (sku),
                INDEX idx_my_name (name(100)),
                INDEX idx_my_session (scrape_session),
                FOREIGN KEY (scrape_session) REFERENCES scrape_sessions(session_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.commit()
        logger.info("Database tables initialized successfully")
    except mysql.connector.Error as err:
        logger.error(f"Error initializing database: {err}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


# Scrape Session Operations
def create_scrape_session(scrape_type: str, store_name: Optional[str] = None) -> str:
    """Create a new scrape session and return its ID."""
    session_id = f"{scrape_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO scrape_sessions (session_id, scrape_type, store_name)
            VALUES (%s, %s, %s)
        """, (session_id, scrape_type, store_name))
        conn.commit()
        logger.info(f"Created scrape session: {session_id}")
        return session_id
    except mysql.connector.Error as err:
        logger.error(f"Error creating scrape session: {err}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def complete_scrape_session(session_id: str, items_count: int):
    """Mark a scrape session as complete."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE scrape_sessions
            SET completed_at = NOW(), items_count = %s
            WHERE session_id = %s
        """, (items_count, session_id))
        conn.commit()
        logger.info(f"Completed scrape session: {session_id} with {items_count} items")
    except mysql.connector.Error as err:
        logger.error(f"Error completing scrape session: {err}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def get_latest_session(scrape_type: str) -> Optional[str]:
    """Get the most recent completed session ID for a scrape type."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT session_id FROM scrape_sessions
            WHERE scrape_type = %s AND completed_at IS NOT NULL
            ORDER BY started_at DESC LIMIT 1
        """, (scrape_type,))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        cursor.close()
        conn.close()


def get_all_sessions(scrape_type: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Get all scrape sessions, optionally filtered by type."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if scrape_type:
            cursor.execute("""
                SELECT * FROM scrape_sessions
                WHERE scrape_type = %s
                ORDER BY started_at DESC LIMIT %s
            """, (scrape_type, limit))
        else:
            cursor.execute("""
                SELECT * FROM scrape_sessions
                ORDER BY started_at DESC LIMIT %s
            """, (limit,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# WTB Listings Operations
def insert_wtb_listing(name: str, scrape_session: str, sku: Optional[str] = None,
                       brand: Optional[str] = None, size: Optional[str] = None,
                       price_min: Optional[float] = None, price_max: Optional[float] = None,
                       store_name: Optional[str] = None, image_url: Optional[str] = None):
    """Insert a new WTB listing (always insert, preserving history)."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO wtb_listings
            (sku, name, brand, size, price_min, price_max, store_name, image_url, scrape_session)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (sku, name, brand, size, price_min, price_max, store_name, image_url, scrape_session))
        conn.commit()
    except mysql.connector.Error as err:
        logger.error(f"Error inserting WTB listing: {err}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def insert_wtb_listings_batch(listings: list[dict], scrape_session: str, batch_size: int = 100):
    """Insert multiple WTB listings in batches to avoid packet size limits."""
    if not listings:
        return

    total_inserted = 0

    # Process in smaller batches
    for i in range(0, len(listings), batch_size):
        batch = listings[i:i + batch_size]

        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.executemany("""
                INSERT INTO wtb_listings
                (sku, name, brand, size, price_min, price_max, store_name, image_url, scrape_session)
                VALUES (%(sku)s, %(name)s, %(brand)s, %(size)s, %(price_min)s, %(price_max)s,
                        %(store_name)s, %(image_url)s, %(scrape_session)s)
            """, [{**item, 'scrape_session': scrape_session} for item in batch])
            conn.commit()
            total_inserted += len(batch)
        except mysql.connector.Error as err:
            logger.error(f"Error batch inserting WTB listings: {err}")
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    logger.debug(f"Inserted {total_inserted} WTB listings in {(len(listings) + batch_size - 1) // batch_size} batches")


def get_all_wtb_listings(session_id: Optional[str] = None) -> list[dict]:
    """Get all WTB listings, optionally filtered by session. Defaults to latest session."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if session_id is None:
            session_id = get_latest_session('wtb')

        if session_id:
            cursor.execute("""
                SELECT id, sku, name, brand, size, price_min, price_max, store_name,
                       store_count, image_url, scrape_session, last_seen, created_at
                FROM wtb_listings
                WHERE scrape_session = %s
                ORDER BY name
            """, (session_id,))
        else:
            # No sessions yet, return empty
            return []

        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_wtb_demand_summary(session_id: Optional[str] = None) -> list[dict]:
    """Get WTB listings grouped by SKU/name with demand count. Defaults to latest session."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if session_id is None:
            session_id = get_latest_session('wtb')

        if not session_id:
            return []

        cursor.execute("""
            SELECT
                COALESCE(sku, name) as identifier,
                name,
                sku,
                brand,
                COUNT(*) as demand_count,
                GROUP_CONCAT(DISTINCT store_name SEPARATOR ', ') as stores,
                MIN(price_min) as min_price,
                MAX(price_max) as max_price,
                GROUP_CONCAT(DISTINCT size SEPARATOR ', ') as sizes,
                MAX(image_url) as image_url
            FROM wtb_listings
            WHERE scrape_session = %s
            GROUP BY COALESCE(sku, name), name, sku, brand
            ORDER BY demand_count DESC
        """, (session_id,))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_wtb_count(session_id: Optional[str] = None) -> int:
    """Get count of WTB listings. Defaults to latest session."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        if session_id is None:
            session_id = get_latest_session('wtb')

        if not session_id:
            return 0

        cursor.execute("SELECT COUNT(*) FROM wtb_listings WHERE scrape_session = %s", (session_id,))
        return cursor.fetchone()[0]
    finally:
        cursor.close()
        conn.close()


# Legacy function - kept for backward compatibility but does nothing harmful
def clear_wtb_listings():
    """Legacy function - no longer clears data. Data is preserved with sessions."""
    logger.warning("clear_wtb_listings() called but data clearing is disabled. Use scrape sessions instead.")
    pass


# My Products Operations
def insert_my_product(name: str, scrape_session: str, sku: Optional[str] = None,
                      brand: Optional[str] = None, sizes: Optional[list] = None,
                      price: Optional[float] = None, url: Optional[str] = None,
                      image_url: Optional[str] = None):
    """Insert a product (always insert, preserving history)."""
    conn = get_connection()
    cursor = conn.cursor()
    sizes_json = json.dumps(sizes) if sizes else None

    try:
        cursor.execute("""
            INSERT INTO my_products
            (sku, name, brand, sizes, price, url, image_url, scrape_session)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (sku, name, brand, sizes_json, price, url, image_url, scrape_session))
        conn.commit()
    except mysql.connector.Error as err:
        logger.error(f"Error inserting product: {err}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def insert_my_products_batch(products: list[dict], scrape_session: str, batch_size: int = 100):
    """Insert multiple products in batches to avoid packet size limits."""
    if not products:
        return

    total_inserted = 0

    # Process in smaller batches
    for i in range(0, len(products), batch_size):
        batch = products[i:i + batch_size]

        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Prepare data with JSON serialized sizes
            prepared = []
            for p in batch:
                item = p.copy()
                item['sizes'] = json.dumps(p.get('sizes')) if p.get('sizes') else None
                item['scrape_session'] = scrape_session
                prepared.append(item)

            cursor.executemany("""
                INSERT INTO my_products
                (sku, name, brand, sizes, price, url, image_url, scrape_session)
                VALUES (%(sku)s, %(name)s, %(brand)s, %(sizes)s, %(price)s, %(url)s,
                        %(image_url)s, %(scrape_session)s)
            """, prepared)
            conn.commit()
            total_inserted += len(batch)
        except mysql.connector.Error as err:
            logger.error(f"Error batch inserting products: {err}")
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    logger.debug(f"Inserted {total_inserted} products in {(len(products) + batch_size - 1) // batch_size} batches")


def get_all_my_products(session_id: Optional[str] = None) -> list[dict]:
    """Get all products from my store. Defaults to latest session."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if session_id is None:
            session_id = get_latest_session('products')

        if not session_id:
            return []

        cursor.execute("""
            SELECT id, sku, name, brand, sizes, price, url, image_url,
                   scrape_session, last_updated
            FROM my_products
            WHERE scrape_session = %s
            ORDER BY name
        """, (session_id,))

        results = []
        for row in cursor.fetchall():
            if row['sizes']:
                row['sizes'] = json.loads(row['sizes'])
            results.append(row)
        return results
    finally:
        cursor.close()
        conn.close()


def get_my_products_count(session_id: Optional[str] = None) -> int:
    """Get count of my products. Defaults to latest session."""
    conn = get_connection()
    cursor = conn.cursor()

    try:
        if session_id is None:
            session_id = get_latest_session('products')

        if not session_id:
            return 0

        cursor.execute("SELECT COUNT(*) FROM my_products WHERE scrape_session = %s", (session_id,))
        return cursor.fetchone()[0]
    finally:
        cursor.close()
        conn.close()


# Legacy function - kept for backward compatibility but does nothing harmful
def clear_my_products():
    """Legacy function - no longer clears data. Data is preserved with sessions."""
    logger.warning("clear_my_products() called but data clearing is disabled. Use scrape sessions instead.")
    pass


# Initialize database on import
try:
    init_database()
except Exception as e:
    logger.error(f"Failed to initialize database on import: {e}")
    logger.info("Make sure MySQL is running and credentials in .env are correct")
