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

    try {
        console.error(`[Progress] Loading ${storeName} (${url})...`);
        await page.goto(url, { waitUntil: 'networkidle', timeout: 90000 });

        // Add human-like behavior
        await humanBehavior(page);
        await page.waitForTimeout(randomDelay(2000, 4000));

        // Wait for Vercel security check to complete
        console.error(`[Progress] Waiting for security verification...`);
        let attempts = 0;
        const maxAttempts = 12; // 60 seconds total

        while (attempts < maxAttempts) {
            const pageText = await page.evaluate(() => document.body.innerText);

            // Check if still verifying
            if (pageText.includes('verifying your browser') || pageText.includes('Vercel Security')) {
                console.error(`[Progress] Still verifying... (attempt ${attempts + 1}/${maxAttempts})`);
                // Add human-like behavior while waiting
                await humanBehavior(page);
                await page.waitForTimeout(randomDelay(3000, 6000));
                attempts++;
                continue;
            }

            // Check if failed
            if (pageText.includes('Failed to verify')) {
                console.error(`[Warning] Verification failed, refreshing...`);
                await page.waitForTimeout(3000);
                await page.reload({ waitUntil: 'networkidle' });
                attempts++;
                continue;
            }

            // Verification passed - page loaded
            console.error(`[Progress] Security check passed!`);
            break;
        }

        await page.waitForTimeout(3000);

        const brands = ['adidas', 'Nike', 'Jordan', 'Yeezy', 'New Balance', 'Puma', 'Reebok', 'Asics', 'Converse', 'Vans', 'UGG', 'Salomon', 'ASICS', 'Saucony', 'On Running', 'HOKA'];

        // Find all clickable product cards - the actual product cards have cursor-pointer and min-h classes
        const cardSelectors = [
            'div[class*="cursor-pointer"][class*="min-h"]',
            'div.cursor-pointer.group',
            '[class*="cursor-pointer"][class*="flex-col"]'
        ];

        // Find product cards using the first selector that works
        let cards = [];
        let workingSelector = cardSelectors[0];
        for (const selector of cardSelectors) {
            cards = await page.$$(selector);
            if (cards.length > 2) {
                workingSelector = selector;
                console.error(`[Progress] Found ${cards.length} cards using selector: ${selector}`);
                break;
            }
        }

        // If we found clickable cards, click each one to get SKU from modal
        if (cards.length > 2) {
            console.error(`[Progress] Clicking ${cards.length} cards to extract SKU from modals...`);

            for (let cardIndex = 0; cardIndex < cards.length; cardIndex++) {
                try {
                    // Re-query cards since DOM might change after modal close
                    const currentCards = await page.$$(workingSelector);
                    if (cardIndex >= currentCards.length) break;

                    const card = currentCards[cardIndex];

                    // Get card text and image before clicking
                    const cardData = await card.evaluate(el => {
                        const text = el.innerText || '';
                        const img = el.querySelector('img');
                        const imageUrl = img ? (img.src || img.dataset?.src || null) : null;
                        return { text, imageUrl };
                    });
                    const cardText = cardData.text;
                    const cardImage = cardData.imageUrl;

                    // Check if this card contains a sneaker brand
                    const hasBrand = brands.some(b => cardText.toLowerCase().includes(b.toLowerCase()));
                    if (!hasBrand || cardText.length < 5) continue;

                    // Extract name from card (first meaningful line that contains a brand)
                    const cardLines = cardText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
                    let name = '';
                    for (const line of cardLines) {
                        if (brands.some(b => line.toLowerCase().includes(b.toLowerCase())) && line.length > 5) {
                            name = line;
                            break;
                        }
                    }
                    if (!name) continue;

                    // Click the card to open modal
                    await card.click();
                    await page.waitForTimeout(500);

                    // Wait for modal to appear and extract data
                    let sku = null;
                    let size = null;

                    try {
                        // Wait for modal animation to complete (needs ~1.5s)
                        await page.waitForTimeout(1500);

                        // Extract SKU from modal dialog
                        const modalData = await page.evaluate(() => {
                            // The modal appears with role="dialog"
                            const modal = document.querySelector('[role="dialog"]');
                            const text = modal ? modal.innerText : document.body.innerText;

                            let sku = null;
                            let size = null;

                            // Look for SKU patterns - "SKU: IE9837" format
                            const skuMatch = text.match(/SKU[:\s]*([A-Z0-9][\w-]+)/i) ||
                                           text.match(/Style[:\s]*([A-Z0-9][\w-]+)/i) ||
                                           text.match(/Article[:\s]*([A-Z0-9][\w-]+)/i);
                            if (skuMatch) {
                                sku = skuMatch[1].toUpperCase();
                            }

                            // Look for sizes section - format is "Sizes" followed by sizes
                            const sizesMatch = text.match(/Sizes?\s*\n\s*([\d.,\/\s\+x]+)/i);
                            if (sizesMatch) {
                                size = sizesMatch[1].trim();
                            }

                            return { sku, size };
                        });

                        sku = modalData.sku;
                        size = modalData.size;

                        // Close modal - try clicking outside or close button
                        const closeBtn = await page.$('[class*="close"], [aria-label="Close"], button:has-text("×"), button:has-text("Close")');
                        if (closeBtn) {
                            await closeBtn.click();
                        } else {
                            // Click outside modal or press Escape
                            await page.keyboard.press('Escape');
                        }
                        await page.waitForTimeout(200);

                    } catch (modalError) {
                        // Modal didn't open or couldn't extract, continue
                        await page.keyboard.press('Escape');
                        await page.waitForTimeout(100);
                    }

                    // Determine brand
                    let brand = null;
                    for (const b of brands) {
                        if (name.toLowerCase().includes(b.toLowerCase())) {
                            brand = b;
                            break;
                        }
                    }

                    const item = {
                        name: name,
                        sku: sku,
                        brand: brand,
                        size: size,
                        price_min: null,
                        price_max: null,
                        store_name: storeName,
                        image_url: cardImage
                    };

                    items.push(item);

                    // Log every 5 cards
                    if ((cardIndex + 1) % 5 === 0 || cardIndex === 0) {
                        console.error(`[Progress] Processed ${cardIndex + 1}/${cards.length} cards (found ${items.length} sneakers)...`);
                    }

                } catch (cardError) {
                    console.error(`[Warning] Error processing card ${cardIndex}: ${cardError.message}`);
                    await page.keyboard.press('Escape');
                    await page.waitForTimeout(100);
                }
            }
        } else {
            // Fallback to text-based parsing if no cards found
            console.error(`[Progress] No cards found, falling back to text parsing...`);
            const pageText = await page.evaluate(() => document.body.innerText);
            const lines = pageText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
            const skipWords = ['WTBs', 'Clear', 'Filter by', 'Sort by', 'My Inventory', 'WTB MARKET', 'WTB Market', '©', 'Search by'];

            let i = 0;
            while (i < lines.length) {
                const line = lines[i];
                if (skipWords.some(w => line.includes(w))) { i++; continue; }

                const isSneakerName = brands.some(b => line.toLowerCase().includes(b.toLowerCase()));
                if (isSneakerName && line.length > 5) {
                    let brand = null;
                    for (const b of brands) {
                        if (line.toLowerCase().includes(b.toLowerCase())) { brand = b; break; }
                    }

                    let size = null;
                    if (i + 1 < lines.length && lines[i + 1] === 'Size:' && i + 2 < lines.length) {
                        size = lines[i + 2];
                        i += 2;
                    } else if (i + 1 < lines.length && /^\d/.test(lines[i + 1])) {
                        size = lines[i + 1];
                        i++;
                    }

                    items.push({
                        name: line, sku: null, brand: brand, size: size,
                        price_min: null, price_max: null, store_name: storeName, image_url: null
                    });
                }
                i++;
            }
        }

        console.error(`[Progress] Found ${items.length} sneakers from ${storeName}`);

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
