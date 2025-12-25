/**
 * WTB Scraper using Playwright (Node.js)
 * Scrapes wtbmarketlist.eu store pages
 * Supports headless mode for VPS deployment
 */
const { chromium } = require('playwright-extra');
const stealth = require('puppeteer-extra-plugin-stealth')();
chromium.use(stealth);
const fs = require('fs');
const path = require('path');

const DELAY_BETWEEN_STORES = 5000;
const IS_HEADLESS = process.env.HEADLESS !== 'false';
const COOKIES_FILE = path.join(__dirname, 'cookies.json');

// User agent rotation
const USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
];

function getRandomUserAgent() {
    return USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
}

function randomDelay(min = 1000, max = 3000) {
    return Math.floor(Math.random() * (max - min)) + min;
}

async function humanBehavior(page) {
    // Random mouse movements
    const x = Math.floor(Math.random() * 800) + 100;
    const y = Math.floor(Math.random() * 400) + 100;
    await page.mouse.move(x, y);
    await page.waitForTimeout(randomDelay(500, 1500));

    // Random scroll
    const scrollY = Math.floor(Math.random() * 300) + 50;
    await page.evaluate((y) => window.scrollTo(0, y), scrollY);
    await page.waitForTimeout(randomDelay(500, 1000));
}

// Load saved cookies if they exist
function loadCookies() {
    if (fs.existsSync(COOKIES_FILE)) {
        const data = JSON.parse(fs.readFileSync(COOKIES_FILE, 'utf-8'));
        // Check if cookies are less than 50 minutes old
        if (Date.now() - data.timestamp < 50 * 60 * 1000) {
            console.error('[Progress] Loading saved cookies...');
            return data.cookies;
        }
        console.error('[Progress] Cookies expired, need fresh verification');
    }
    return null;
}

// Save cookies after successful verification
function saveCookies(cookies) {
    fs.writeFileSync(COOKIES_FILE, JSON.stringify({
        timestamp: Date.now(),
        cookies: cookies
    }));
    console.error('[Progress] Cookies saved for future runs');
}

async function scrapeStore(page, url, storeName) {
    const items = [];
    const seenNames = new Set(); // Track seen items to avoid duplicates

    const brands = ['adidas', 'Nike', 'Jordan', 'Yeezy', 'New Balance', 'Puma', 'Reebok', 'Asics', 'ASICS', 'Converse', 'Vans', 'UGG', 'Salomon', 'Saucony', 'On Running', 'HOKA', 'Crocs', 'Timberland', 'Dr. Martens', 'Balenciaga', 'Gucci', 'Louis Vuitton', 'Off-White', 'Fear of God', 'Supreme', 'Stussy', 'A Bathing Ape', 'BAPE', 'Travis Scott', 'Dunk', 'Air Force', 'Air Max', 'Air Jordan', 'Kobe', 'LeBron', 'KD', 'Kyrie', 'Sacai', 'Union', 'Fragment', 'Comme des Garcons', 'CDG', 'Palace', 'Kith', 'Aime Leon Dore', 'ALD', 'Maison Margiela', 'Rick Owens', 'Axel Arigato', 'Common Projects', 'Golden Goose', 'Versace', 'Prada', 'Dior', 'Burberry', 'Fendi', 'Valentino', 'Givenchy', 'Alexander McQueen', 'Bottega Veneta', 'Loewe', 'Celine', 'Saint Laurent', 'Moncler', 'Stone Island', 'CP Company', 'Acne Studios', 'JW Anderson', 'Wales Bonner', 'Jacquemus', 'Palm Angels', 'Amiri', 'Represent', 'Essentials', 'Fear Of God', 'FOG', 'Chrome Hearts', 'Gallery Dept', 'Rhude'];

    const cardSelectors = [
        'div[class*="cursor-pointer"][class*="min-h"]',
        'div.cursor-pointer.group',
        '[class*="cursor-pointer"][class*="flex-col"]'
    ];

    // Helper function to wait for security check
    async function waitForSecurityCheck() {
        console.error(`[Progress] Waiting for security verification...`);
        let attempts = 0;
        const maxAttempts = 12;

        while (attempts < maxAttempts) {
            const pageText = await page.evaluate(() => document.body.innerText);

            if (pageText.includes('verifying your browser') || pageText.includes('Vercel Security')) {
                console.error(`[Progress] Still verifying... (attempt ${attempts + 1}/${maxAttempts})`);
                await humanBehavior(page);
                await page.waitForTimeout(randomDelay(3000, 6000));
                attempts++;
                continue;
            }

            if (pageText.includes('Failed to verify')) {
                console.error(`[Warning] Verification failed, refreshing...`);
                await page.waitForTimeout(3000);
                await page.reload({ waitUntil: 'networkidle' });
                attempts++;
                continue;
            }

            console.error(`[Progress] Security check passed!`);
            return true;
        }
        return false;
    }

    // Helper function to extract items from current page
    async function extractItemsFromPage(pageNum) {
        const pageItems = [];
        let workingSelector = cardSelectors[0];
        let cards = [];

        for (const selector of cardSelectors) {
            cards = await page.$$(selector);
            if (cards.length > 2) {
                workingSelector = selector;
                break;
            }
        }

        if (cards.length === 0) {
            return pageItems;
        }

        for (let cardIndex = 0; cardIndex < cards.length; cardIndex++) {
            try {
                const currentCards = await page.$$(workingSelector);
                if (cardIndex >= currentCards.length) break;

                const card = currentCards[cardIndex];
                const cardData = await card.evaluate(el => {
                    const text = el.innerText || '';
                    const img = el.querySelector('img');
                    const imageUrl = img ? (img.src || img.dataset?.src || null) : null;
                    return { text, imageUrl };
                });
                const cardText = cardData.text;
                const cardImage = cardData.imageUrl;

                if (cardText.length < 5) continue;

                const cardLines = cardText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                let name = '';
                for (const line of cardLines) {
                    if (line.length > 5 && /[a-zA-Z]/.test(line)) {
                        name = line;
                        break;
                    }
                }
                if (!name) continue;

                // Skip duplicates
                if (seenNames.has(name)) continue;
                seenNames.add(name);

                // Extract SKU from card text
                let sku = null;
                const skuMatch = cardText.match(/\b([A-Z]{1,2}\d{4,})\b/) ||
                                cardText.match(/\b(\d{6}[-\s]?\d{3})\b/);
                if (skuMatch) {
                    sku = skuMatch[1].toUpperCase();
                }

                // Extract size from card
                let size = null;
                const sizeMatch = cardText.match(/Size[:\s]*\n?\s*([\d\s\/,\.x\+]+)/i);
                if (sizeMatch) {
                    size = sizeMatch[1].trim();
                }

                // Determine brand
                let brand = null;
                for (const b of brands) {
                    if (name.toLowerCase().includes(b.toLowerCase())) {
                        brand = b;
                        break;
                    }
                }

                pageItems.push({
                    name: name,
                    sku: sku,
                    brand: brand,
                    size: size,
                    price_min: null,
                    price_max: null,
                    store_name: storeName,
                    image_url: cardImage
                });

            } catch (cardError) {
                // Continue on card errors
            }
        }

        return pageItems;
    }

    try {
        // Use URL-based pagination - load each page
        let pageNum = 1;
        const maxPages = 50; // Safety limit
        let emptyPageCount = 0;
        let totalEstimate = '?';

        console.error(`[Progress] Loading ${storeName} with pagination...`);
        console.error(`[Status] phase=loading|current=0|total=?|message=Starting pagination...`);

        while (pageNum <= maxPages) {
            const pageUrl = pageNum === 1 ? url : `${url}?page=${pageNum}`;
            console.error(`[Progress] Loading page ${pageNum}...`);

            try {
                await page.goto(pageUrl, { waitUntil: 'networkidle', timeout: 30000 });
            } catch (navError) {
                console.error(`[Warning] Page ${pageNum} navigation timeout, stopping pagination`);
                break;
            }
            await humanBehavior(page);
            await page.waitForTimeout(randomDelay(1000, 2000));

            // Security check on first page
            if (pageNum === 1) {
                const passed = await waitForSecurityCheck();
                if (!passed) {
                    console.error(`[Error] Security check failed for ${storeName}`);
                    break;
                }
                await page.waitForTimeout(2000);
            }

            // Extract items from this page
            const beforeCount = items.length;
            const pageItems = await extractItemsFromPage(pageNum);
            items.push(...pageItems);

            const newItems = items.length - beforeCount;
            console.error(`[Progress] Page ${pageNum}: found ${pageItems.length} cards, ${newItems} new items (total: ${items.length})`);
            console.error(`[Status] phase=loading|current=${items.length}|total=${totalEstimate}|message=Page ${pageNum}: ${items.length} items found`);

            // Check if we should stop - stop immediately if page has few items (near end)
            if (pageItems.length === 0 || newItems === 0) {
                console.error(`[Progress] No new items found on page ${pageNum}, stopping`);
                break;
            }

            // Also stop if this page had significantly fewer items than a full page
            if (pageItems.length < 20 && pageNum > 1) {
                console.error(`[Progress] Last page detected (only ${pageItems.length} items), stopping`);
                break;
            }

            pageNum++;

            // Small delay between pages
            if (pageNum <= maxPages) {
                await page.waitForTimeout(randomDelay(1000, 2000));
            }
        }

        console.error(`[Progress] Found ${items.length} sneakers from ${storeName} (${pageNum - 1} pages)`);
        console.error(`[Status] phase=complete|current=${items.length}|total=${items.length}|message=Complete! Found ${items.length} sneakers from ${storeName}`);

    } catch (error) {
        console.error(`[Error] ${storeName}: ${error.message}`);
    }

    return items;
}

async function scrapeMultipleStores(stores) {
    const allItems = [];

    // Chromium with stealth plugin
    const browser = await chromium.launch({
        headless: IS_HEADLESS,
        args: [
            '--disable-blink-features=AutomationControlled',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-web-security',
            '--window-size=1920,1080'
        ]
    });

    const userAgent = getRandomUserAgent();
    console.error(`[Progress] Using user agent: ${userAgent.substring(0, 50)}...`);

    const context = await browser.newContext({
        userAgent: userAgent,
        viewport: { width: 1920, height: 1080 },
        locale: 'en-US',
        timezoneId: 'Europe/Copenhagen'
    });

    // Load saved cookies if available
    const savedCookies = loadCookies();
    if (savedCookies) {
        await context.addCookies(savedCookies);
    }

    // Add stealth scripts
    await context.addInitScript(() => {
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    });

    const page = await context.newPage();
    let cookiesSaved = false;

    try {
        for (let i = 0; i < stores.length; i++) {
            const store = stores[i];
            console.error(`[Progress] Scraping store ${i + 1}/${stores.length}: ${store.name}`);

            const items = await scrapeStore(page, store.url, store.name);
            allItems.push(...items);

            // Save cookies after first successful scrape
            if (items.length > 0 && !cookiesSaved) {
                const cookies = await context.cookies();
                saveCookies(cookies);
                cookiesSaved = true;
            }

            if (i < stores.length - 1) {
                console.error(`[Progress] Waiting ${DELAY_BETWEEN_STORES/1000}s before next store...`);
                await page.waitForTimeout(DELAY_BETWEEN_STORES);
            }
        }
    } finally {
        await browser.close();
    }

    console.error(`[Progress] Total: ${allItems.length} sneakers from ${stores.length} stores`);
    return allItems;
}

async function authenticate() {
    // Run visible browser for manual verification
    console.error('[Auth] Opening browser for manual verification...');
    console.error('[Auth] Please wait for the page to load and pass the security check.');

    const browser = await chromium.launch({ headless: false });
    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        viewport: { width: 1920, height: 1080 }
    });

    const page = await context.newPage();
    await page.goto('https://www.wtbmarketlist.eu/store/adonio', { waitUntil: 'networkidle', timeout: 120000 });

    // Wait for user to pass verification (check for sneaker content)
    console.error('[Auth] Waiting for security check to pass...');
    let passed = false;
    for (let i = 0; i < 60; i++) { // Wait up to 5 minutes
        await page.waitForTimeout(5000);
        const text = await page.evaluate(() => document.body.innerText);
        if (text.includes('Nike') || text.includes('Jordan') || text.includes('adidas') || text.includes('Yeezy')) {
            passed = true;
            break;
        }
        console.error(`[Auth] Still waiting... (${i + 1}/60)`);
    }

    if (passed) {
        const cookies = await context.cookies();
        saveCookies(cookies);
        console.error('[Auth] SUCCESS! Cookies saved. You can now run automated scrapes.');
    } else {
        console.error('[Auth] FAILED - Could not verify. Try again.');
    }

    await browser.close();
}

async function main() {
    const args = process.argv.slice(2);

    // Auth mode - generate cookies manually
    if (args.includes('--auth')) {
        await authenticate();
        return;
    }

    let stores = [];

    if (args.includes('--all')) {
        const storesFile = path.join(__dirname, 'stores.json');
        if (fs.existsSync(storesFile)) {
            const config = JSON.parse(fs.readFileSync(storesFile, 'utf-8'));
            stores = config.stores.filter(s => s.enabled);
            console.error(`[Progress] Loading ${stores.length} stores from stores.json`);
        } else {
            console.error('[Error] stores.json not found');
            process.exit(1);
        }
    } else if (args.length > 0 && args[0].startsWith('http')) {
        const url = args[0];
        const storeName = url.split('/store/')[1] || 'unknown';
        stores = [{ name: storeName, url: url }];
    } else {
        stores = [{
            name: 'adonio',
            url: 'https://www.wtbmarketlist.eu/store/adonio'
        }];
    }

    const items = await scrapeMultipleStores(stores);
    console.log(JSON.stringify(items, null, 2));
}

main().catch(err => {
    console.error(`[Fatal] ${err.message}`);
    process.exit(1);
});
