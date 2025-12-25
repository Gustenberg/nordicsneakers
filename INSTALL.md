# Nordic Sneakers WTB Monitor - Installation

## Krav
- Ubuntu 20.04+ server (eller lignende Linux distribution)
- Python 3.10+
- Node.js 18+
- Root adgang (til systemd service)

## Hurtig Installation

```bash
# 1. Upload filer til server (fra din lokale maskine)
scp -r Nordicsneakers user@din-server:/home/user/

# 2. SSH ind på serveren
ssh user@din-server

# 3. Gå til app mappe
cd /home/user/Nordicsneakers

# 4. Kopier og konfigurer miljøfil
cp .env.example .env
nano .env
# Indsæt din Nordic Sneakers session cookie

# 5. Kør opsætning
sudo bash setup.sh

# 6. Start tjenesten
sudo systemctl start nordic-sneakers
```

## Manuel Installation

Hvis du foretrækker manuel opsætning:

```bash
# Python afhængigheder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Node.js afhængigheder
npm install
npx playwright install chromium

# Start applikationen
python main.py
```

## Hent Din Cookie

1. Log ind på https://nordicsneakers.dk/seller
2. Åbn browser DevTools (F12) → Application → Cookies
3. Kopier `session` cookie værdien
4. Indsæt i `.env` fil:
   ```
   NORDIC_SNEAKERS_COOKIE=.eJxl...din_cookie...
   ```

## Kommandoer

| Handling | Kommando |
|----------|----------|
| Start | `sudo systemctl start nordic-sneakers` |
| Stop | `sudo systemctl stop nordic-sneakers` |
| Genstart | `sudo systemctl restart nordic-sneakers` |
| Status | `sudo systemctl status nordic-sneakers` |
| Logs | `sudo journalctl -u nordic-sneakers -f` |

## Adgang til Dashboard

Åbn i browser: `http://DIN_SERVER_IP:8000`

### Endpoints

| Endpoint | Beskrivelse |
|----------|-------------|
| `/` | Hoved dashboard |
| `/health` | Simpelt sundhedstjek |
| `/api/health` | Detaljeret sundhedstjek med database status |
| `/api/status` | Scraping status |
| `/api/comparison` | Sammenligningsresultater (JSON) |

## Firewall

Hvis du bruger UFW:
```bash
sudo ufw allow 8000
```

## Opdater Cookie

Når din session udløber:
```bash
nano /home/user/Nordicsneakers/.env
# Opdater cookie værdien
sudo systemctl restart nordic-sneakers
```

## Logs

Applikationen logger til:
- Konsol (altid)
- `logs/app.log` (kun i produktion)

Se logfil:
```bash
tail -f /home/user/Nordicsneakers/logs/app.log
```

## Miljøvariabler

Se `.env.example` for alle tilgængelige konfigurationsmuligheder:

| Variabel | Beskrivelse | Standard |
|----------|-------------|----------|
| `NORDIC_SNEAKERS_COOKIE` | Session cookie (påkrævet) | - |
| `MY_STORE_TYPE` | Butikstype | `nordic_sneakers` |
| `HOST` | Server bind adresse | `0.0.0.0` |
| `PORT` | Server port | `8000` |
| `APP_ENV` | Miljø (development/production) | `production` |
| `LOG_LEVEL` | Log niveau | `INFO` |

## Fejlfinding

### Cookie udløbet
```
Nordic Sneakers godkendelse fejlede. Cookie kan være udløbet.
```
→ Hent ny cookie fra browser og opdater `.env`

### Scraper timeout
```
Scrape timeout efter 10 minutter
```
→ Vercel sikkerhedstjek kan tage lang tid. Prøv at køre `node scraper.js --auth` for manuel godkendelse.

### Port allerede i brug
```
Address already in use
```
→ Skift PORT i `.env` eller stop eksisterende proces: `sudo lsof -i :8000`
