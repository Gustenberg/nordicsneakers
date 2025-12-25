"""
WTB Market Monitor - FastAPI Backend med Planlagt Scraping
"""
import asyncio
import csv
import io
import json
from datetime import datetime
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import HOST, PORT, BASE_DIR, APP_ENV, logger
import database
from scrapers import WTBScraper, StoreScraper
from services import ComparisonService

# Initialiser FastAPI app
app = FastAPI(
    title="WTB Market Monitor",
    version="1.0.0",
    docs_url="/api/docs" if APP_ENV != "production" else None,
    redoc_url="/api/redoc" if APP_ENV != "production" else None
)

# Mount statiske filer og templates
static_path = BASE_DIR / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Stier
STORES_FILE = BASE_DIR / "stores.json"

# Trådsikker global state
_state_lock = Lock()
scrape_status = {
    "wtb": {"running": False, "progress": "", "last_run": None, "count": 0},
    "store": {"running": False, "progress": "", "last_run": None, "count": 0}
}

# Comparison cache
_cache_lock = Lock()
comparison_cache = {
    "results": None,
    "last_updated": None
}

# Console log buffer for UI
_log_lock = Lock()
console_logs = []
log_index = 0

def add_console_log(message: str):
    """Add a log message to the console buffer."""
    global log_index
    with _log_lock:
        log_index += 1
        console_logs.append({
            "index": log_index,
            "timestamp": datetime.now().isoformat(),
            "message": message
        })
        # Keep only last 200 messages
        if len(console_logs) > 200:
            console_logs.pop(0)

def get_console_logs(since_index: int = 0):
    """Get logs since a given index."""
    with _log_lock:
        return [log for log in console_logs if log["index"] > since_index], log_index


def update_scrape_status(scrape_type: str, **kwargs):
    """Trådsikker opdatering af scrape status."""
    with _state_lock:
        for key, value in kwargs.items():
            scrape_status[scrape_type][key] = value


def get_scrape_status(scrape_type: str = None) -> dict:
    """Trådsikker hentning af scrape status."""
    with _state_lock:
        if scrape_type:
            return dict(scrape_status[scrape_type])
        return {k: dict(v) for k, v in scrape_status.items()}


def get_cached_comparison():
    """Hent sammenligning, brug cache hvis tilgængelig."""
    with _cache_lock:
        if comparison_cache["results"] is None:
            service = ComparisonService()
            comparison_cache["results"] = service.compare()
            comparison_cache["last_updated"] = datetime.now().isoformat()
        return comparison_cache["results"]


def invalidate_comparison_cache():
    """Invalider comparison cache når data ændres."""
    with _cache_lock:
        comparison_cache["results"] = None
        comparison_cache["last_updated"] = None


# Scheduler
scheduler = AsyncIOScheduler()


# ============ Butik Administration ============

def load_stores_config() -> dict:
    """Indlæs butiks konfiguration fra JSON fil."""
    if STORES_FILE.exists():
        with open(STORES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"stores": [], "schedule": {"enabled": True, "times": ["08:00", "20:00"]}}


def save_stores_config(config: dict):
    """Gem butiks konfiguration til JSON fil."""
    with open(STORES_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)


# ============ Planlagt Scraping ============

async def scheduled_scrape():
    """Kør planlagt scrape af alle aktiverede butikker."""
    if get_scrape_status("wtb")["running"]:
        logger.info("Scrape kører allerede, springer over...")
        return

    logger.info("Starter planlagt WTB scrape")
    add_console_log("WTB: Starter planlagt scrape...")
    update_scrape_status("wtb", running=True, progress="Planlagt scrape starter...")

    try:
        scraper = WTBScraper()

        def progress_callback(msg):
            update_scrape_status("wtb", progress=msg)
            add_console_log(f"WTB: {msg}")
            logger.debug(f"WTB: {msg}")

        items = await scraper.scrape_all_stores(progress_callback=progress_callback)
        scraper.save_to_database(items)

        update_scrape_status(
            "wtb",
            count=len(items),
            last_run=datetime.now().isoformat(),
            progress=f"Planlagt scrape færdig: {len(items)} opslag"
        )
        invalidate_comparison_cache()
        logger.info(f"WTB scrape færdig: {len(items)} opslag fundet")

    except Exception as e:
        update_scrape_status("wtb", progress=f"Fejl: {str(e)}")
        logger.error(f"WTB scrape fejl: {e}")

    finally:
        update_scrape_status("wtb", running=False)


async def scheduled_store_scrape():
    """Kør planlagt scrape af Nordic Sneakers lager."""
    if get_scrape_status("store")["running"]:
        logger.info("Butik scrape kører allerede, springer over...")
        return

    logger.info("Starter planlagt butik scrape")
    add_console_log("Butik: Starter planlagt hentning...")
    update_scrape_status("store", running=True, progress="Planlagt hentning starter...")

    try:
        scraper = StoreScraper(store_type='nordic_sneakers')

        def progress_callback(msg):
            update_scrape_status("store", progress=msg)
            add_console_log(f"Butik: {msg}")
            logger.debug(f"Butik: {msg}")

        items = await scraper.scrape_products(progress_callback=progress_callback)
        scraper.save_to_database(items)

        update_scrape_status(
            "store",
            count=len(items),
            last_run=datetime.now().isoformat(),
            progress=f"Planlagt hentning færdig: {len(items)} produkter"
        )
        invalidate_comparison_cache()
        logger.info(f"Butik scrape færdig: {len(items)} produkter fundet")

    except Exception as e:
        update_scrape_status("store", progress=f"Fejl: {str(e)}")
        logger.error(f"Butik scrape fejl: {e}")

    finally:
        update_scrape_status("store", running=False)


def setup_scheduler():
    """Opsæt planlagte scraping jobs."""
    config = load_stores_config()

    # Fjern eksisterende jobs
    scheduler.remove_all_jobs()

    # WTB Tidsplan
    wtb_schedule = config.get("schedule", {})
    if wtb_schedule.get("enabled", False):
        times = wtb_schedule.get("times", ["08:00", "20:00"])
        for time_str in times:
            hour, minute = map(int, time_str.split(':'))
            scheduler.add_job(
                scheduled_scrape,
                CronTrigger(hour=hour, minute=minute),
                id=f"wtb_scrape_{time_str}",
                replace_existing=True
            )
            logger.info(f"WTB scrape planlagt kl. {time_str}")
    else:
        logger.info("WTB tidsplan er deaktiveret")

    # Butik (Nordic Sneakers) Tidsplan
    store_schedule = config.get("store_schedule", {"enabled": True, "times": ["07:00", "19:00"]})
    if store_schedule.get("enabled", False):
        times = store_schedule.get("times", ["07:00", "19:00"])
        for time_str in times:
            hour, minute = map(int, time_str.split(':'))
            scheduler.add_job(
                scheduled_store_scrape,
                CronTrigger(hour=hour, minute=minute),
                id=f"store_scrape_{time_str}",
                replace_existing=True
            )
            logger.info(f"Butik scrape planlagt kl. {time_str}")
    else:
        logger.info("Butik tidsplan er deaktiveret")


@app.on_event("startup")
async def startup_event():
    """Start scheduler ved app opstart."""
    setup_scheduler()
    scheduler.start()
    logger.info("Applikation startet")


@app.on_event("shutdown")
async def shutdown_event():
    """Stop scheduler ved nedlukning."""
    scheduler.shutdown()
    logger.info("Applikation stoppet")


# ============ Health Check ============

@app.get("/health")
async def health_check():
    """Sundhedstjek endpoint for overvågning."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "environment": APP_ENV
    }


@app.get("/api/health")
async def api_health_check():
    """Detaljeret sundhedstjek med database status."""
    db_ok = False
    try:
        wtb_count = database.get_wtb_count()
        products_count = database.get_my_products_count()
        db_ok = True
    except Exception as e:
        logger.error(f"Database sundhedstjek fejlede: {e}")
        wtb_count = 0
        products_count = 0

    return {
        "status": "healthy" if db_ok else "unhealthy",
        "timestamp": datetime.now().isoformat(),
        "database": {
            "connected": db_ok,
            "wtb_listings": wtb_count,
            "products": products_count
        },
        "scheduler": {
            "running": scheduler.running,
            "jobs": len(scheduler.get_jobs())
        }
    }


# ============ Dashboard Ruter ============

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Hoved dashboard side."""
    results = get_cached_comparison()
    stores_config = load_stores_config()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "results": results,
        "scrape_status": get_scrape_status(),
        "wtb_count": database.get_wtb_count(),
        "my_products_count": database.get_my_products_count(),
        "stores": stores_config.get("stores", []),
        "schedule": stores_config.get("schedule", {}),
        "store_schedule": stores_config.get("store_schedule", {"enabled": True, "times": ["07:00", "19:00"]})
    })


@app.get("/api/status")
async def get_status():
    """Hent nuværende scraping status og antal."""
    return {
        "scrape_status": get_scrape_status(),
        "wtb_count": database.get_wtb_count(),
        "my_products_count": database.get_my_products_count()
    }


@app.get("/api/logs")
async def get_logs(since: int = 0):
    """Hent konsol logs siden et givent indeks."""
    logs, last_index = get_console_logs(since)
    return {
        "logs": logs,
        "last_index": last_index
    }


# ============ Butik Administration Ruter ============

@app.get("/api/stores")
async def get_stores():
    """Hent liste over konfigurerede butikker."""
    config = load_stores_config()
    return config


@app.post("/api/stores")
async def add_store(request: Request):
    """Tilføj en ny butik til scraping."""
    data = await request.json()
    name = data.get("name", "").strip()
    url = data.get("url", "").strip()

    if not name or not url:
        return JSONResponse({"error": "Navn og URL er påkrævet"}, status_code=400)

    if not url.startswith("https://www.wtbmarketlist.eu/store/"):
        return JSONResponse({"error": "URL skal være en wtbmarketlist.eu butik URL"}, status_code=400)

    config = load_stores_config()
    config["stores"].append({
        "name": name,
        "url": url,
        "enabled": True
    })
    save_stores_config(config)
    logger.info(f"Butik tilføjet: {name}")

    return {"message": f"Butik '{name}' tilføjet", "stores": config["stores"]}


@app.delete("/api/stores/{index}")
async def remove_store(index: int):
    """Fjern en butik efter indeks."""
    config = load_stores_config()

    if 0 <= index < len(config["stores"]):
        removed = config["stores"].pop(index)
        save_stores_config(config)
        logger.info(f"Butik fjernet: {removed['name']}")
        return {"message": f"Butik '{removed['name']}' fjernet"}

    return JSONResponse({"error": "Ugyldigt butik indeks"}, status_code=404)


@app.put("/api/stores/{index}/toggle")
async def toggle_store(index: int):
    """Skift en butiks aktiverede status."""
    config = load_stores_config()

    if 0 <= index < len(config["stores"]):
        config["stores"][index]["enabled"] = not config["stores"][index]["enabled"]
        save_stores_config(config)
        return {"message": "Butik skiftet", "enabled": config["stores"][index]["enabled"]}

    return JSONResponse({"error": "Ugyldigt butik indeks"}, status_code=404)


@app.put("/api/schedule")
async def update_schedule(request: Request):
    """Opdater WTB scraping tidsplan."""
    data = await request.json()
    config = load_stores_config()

    config["schedule"]["enabled"] = data.get("enabled", True)
    config["schedule"]["times"] = data.get("times", ["08:00", "20:00"])

    save_stores_config(config)
    setup_scheduler()
    logger.info(f"WTB tidsplan opdateret: {config['schedule']}")

    return {"message": "Tidsplan opdateret", "schedule": config["schedule"]}


@app.put("/api/store-schedule")
async def update_store_schedule(request: Request):
    """Opdater Nordic Sneakers butik scraping tidsplan."""
    data = await request.json()
    config = load_stores_config()

    if "store_schedule" not in config:
        config["store_schedule"] = {"enabled": True, "times": ["07:00", "19:00"]}

    config["store_schedule"]["enabled"] = data.get("enabled", True)
    config["store_schedule"]["times"] = data.get("times", ["07:00", "19:00"])

    save_stores_config(config)
    setup_scheduler()
    logger.info(f"Butik tidsplan opdateret: {config['store_schedule']}")

    return {"message": "Butik tidsplan opdateret", "store_schedule": config["store_schedule"]}


# ============ Scraping Ruter ============

@app.post("/api/scrape/wtb")
async def scrape_wtb(background_tasks: BackgroundTasks):
    """Start WTB scraping i baggrunden."""
    if get_scrape_status("wtb")["running"]:
        return JSONResponse({"error": "WTB scrape kører allerede"}, status_code=400)

    background_tasks.add_task(run_wtb_scrape)
    return {"message": "WTB scrape startet"}


async def run_wtb_scrape():
    """Baggrundsopgave til WTB scrape."""
    add_console_log("WTB: Starter manuel scrape...")
    update_scrape_status("wtb", running=True, progress="Starter...")

    try:
        scraper = WTBScraper()

        def progress_callback(msg):
            update_scrape_status("wtb", progress=msg)
            add_console_log(f"WTB: {msg}")

        items = await scraper.scrape_all_stores(progress_callback=progress_callback)
        scraper.save_to_database(items)

        update_scrape_status(
            "wtb",
            count=len(items),
            last_run=datetime.now().isoformat(),
            progress=f"Færdig: {len(items)} opslag fundet"
        )
        invalidate_comparison_cache()
        add_console_log(f"WTB: Færdig! {len(items)} opslag fundet")
        logger.info(f"Manuel WTB scrape færdig: {len(items)} opslag")

    except Exception as e:
        update_scrape_status("wtb", progress=f"Fejl: {str(e)}")
        add_console_log(f"WTB ERROR: {str(e)}")
        logger.error(f"Manuel WTB scrape fejl: {e}")

    finally:
        update_scrape_status("wtb", running=False)


@app.post("/api/scrape/store")
async def scrape_store(background_tasks: BackgroundTasks):
    """Start butik scraping i baggrunden."""
    if get_scrape_status("store")["running"]:
        return JSONResponse({"error": "Butik scrape kører allerede"}, status_code=400)

    background_tasks.add_task(run_store_scrape)
    return {"message": "Butik scrape startet"}


async def run_store_scrape():
    """Baggrundsopgave til butik scrape."""
    add_console_log("Butik: Starter manuel hentning...")
    update_scrape_status("store", running=True, progress="Starter...")

    try:
        scraper = StoreScraper()

        def progress_callback(msg):
            update_scrape_status("store", progress=msg)
            add_console_log(f"Butik: {msg}")

        items = await scraper.scrape_products(progress_callback=progress_callback)
        scraper.save_to_database(items)

        update_scrape_status(
            "store",
            count=len(items),
            last_run=datetime.now().isoformat(),
            progress=f"Færdig: {len(items)} produkter fundet"
        )
        invalidate_comparison_cache()
        add_console_log(f"Butik: Færdig! {len(items)} produkter fundet")
        logger.info(f"Manuel butik scrape færdig: {len(items)} produkter")

    except Exception as e:
        update_scrape_status("store", progress=f"Fejl: {str(e)}")
        add_console_log(f"Butik ERROR: {str(e)}")
        logger.error(f"Manuel butik scrape fejl: {e}")

    finally:
        update_scrape_status("store", running=False)


@app.post("/api/import/csv")
async def import_csv(file: UploadFile = File(...)):
    """Importer produkter fra CSV fil."""
    try:
        content = await file.read()
        decoded = content.decode('utf-8')

        reader = csv.DictReader(io.StringIO(decoded))
        items = []

        for row in reader:
            item = {
                "name": row.get('name', '').strip(),
                "sku": row.get('sku', '').strip() or None,
                "brand": row.get('brand', '').strip() or None,
                "sizes": row.get('sizes', '').split(',') if row.get('sizes') else None,
                "price": float(row['price']) if row.get('price') else None,
                "url": row.get('url', '').strip() or None
            }
            if item["name"]:
                items.append(item)

        scraper = StoreScraper()
        scraper.save_to_database(items)

        update_scrape_status(
            "store",
            count=len(items),
            last_run=datetime.now().isoformat()
        )
        logger.info(f"CSV import færdig: {len(items)} produkter")

        return {"message": f"Importerede {len(items)} produkter", "count": len(items)}

    except Exception as e:
        logger.error(f"CSV import fejl: {e}")
        return JSONResponse({"error": str(e)}, status_code=400)


# ============ Sammenligning Ruter ============

@app.get("/api/comparison")
async def get_comparison():
    """Hent sammenligningsresultater som JSON (cached)."""
    return get_cached_comparison()


@app.get("/api/comparison/summary")
async def get_comparison_summary():
    """Hent kun sammenlignings oversigt (letvægts til live opdateringer)."""
    results = get_cached_comparison()
    with _cache_lock:
        return {
            "summary": results["summary"],
            "last_updated": comparison_cache["last_updated"]
        }


# ============ Eksport Ruter ============

@app.get("/api/export/missing")
async def export_missing():
    """Eksporter manglende varer som CSV."""
    service = ComparisonService()
    results = service.compare()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Navn", "SKU", "Brand", "Efterspørgsel", "Størrelser Ønsket", "Butik"])

    for item in results["missing"]:
        writer.writerow([
            item.get("wtb_name", ""),
            item.get("wtb_sku", ""),
            item.get("brand", ""),
            item.get("demand_count", 0),
            ",".join(item.get("sizes_wanted", [])),
            ", ".join(item.get("stores_wanting", []))
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=manglende_sneakers.csv"}
    )


@app.get("/api/export/all")
async def export_all():
    """Eksporter alle sammenligningsresultater som CSV."""
    service = ComparisonService()
    results = service.compare()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Status", "Navn", "SKU", "Brand", "Efterspørgsel", "Pris", "URL"])

    for item in results["missing"]:
        writer.writerow([
            "Mangler", item.get("wtb_name", ""), item.get("wtb_sku", ""),
            item.get("brand", ""), item.get("demand_count", 0), "", ""
        ])

    for item in results["in_stock"]:
        writer.writerow([
            "På Lager", item.get("my_product_name", ""), item.get("my_product_sku", ""),
            "", item.get("demand_count", 0), item.get("my_product_price", ""),
            item.get("my_product_url", "")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sammenlignings_resultater.csv"}
    )


# ============ Data Administration Ruter ============

@app.delete("/api/data/wtb")
async def clear_wtb_data():
    """
    Legacy endpoint - data clearing is disabled.
    Historical data is now preserved with session tracking.
    """
    logger.warning("Attempt to clear WTB data - operation disabled (data is preserved)")
    return {
        "message": "Data rydning er deaktiveret. Historiske data bevares med session tracking.",
        "info": "Brug /api/sessions for at se scrape historik"
    }


@app.delete("/api/data/products")
async def clear_products_data():
    """
    Legacy endpoint - data clearing is disabled.
    Historical data is now preserved with session tracking.
    """
    logger.warning("Attempt to clear products data - operation disabled (data is preserved)")
    return {
        "message": "Data rydning er deaktiveret. Historiske data bevares med session tracking.",
        "info": "Brug /api/sessions for at se scrape historik"
    }


@app.get("/api/sessions")
async def get_scrape_sessions(scrape_type: str = None, limit: int = 50):
    """Hent liste over alle scrape sessions."""
    sessions = database.get_all_sessions(scrape_type=scrape_type, limit=limit)
    return {"sessions": sessions}


# ============ Opstart ============

if __name__ == "__main__":
    import uvicorn

    config = load_stores_config()
    schedule = config.get("schedule", {})
    times = schedule.get("times", [])

    logger.info(f"""
╔═══════════════════════════════════════════════════════════╗
║           WTB Market Monitor - Starter...                 ║
╠═══════════════════════════════════════════════════════════╣
║  Dashboard: http://{HOST}:{PORT}
║  Health:    http://{HOST}:{PORT}/health
║                                                           ║
║  Planlagt scraping: {schedule.get('enabled', False)}
║  Scrape tidspunkter: {', '.join(times) if times else 'Ingen'}
╚═══════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(app, host=HOST, port=PORT)
