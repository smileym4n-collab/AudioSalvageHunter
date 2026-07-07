# Audio Salvage Hunter

Audio Salvage Hunter is a Python 3 command-line application for finding promising used, faulty, untested, spares-or-repair and job-lot audio equipment on eBay UK.

It uses the official eBay Buy Browse API. It does not scrape browser pages, bid, buy, message sellers, or add items to watchlists.

The tool is deliberately conservative: when a listing looks like it may contain useful parts, the report describes those parts as possible unless the listing text itself confirms them.

## What It Searches For

The default configuration searches several query groups:

- exact donor equipment models
- component names
- generic fault descriptions
- brand plus equipment category searches

It scores likely salvage value for reusable audio components such as DACs, ADCs, op-amps, volume-control ICs, transformers and power-amplifier parts.

## eBay Developer Account Setup

1. Create or sign in to an eBay Developer account at [developer.ebay.com](https://developer.ebay.com/).
2. Create a Production application keyset.
3. Copy the application Client ID and Client Secret.
4. Make sure the application can call the Buy Browse API.

This app uses:

- OAuth client credentials authentication
- application access tokens
- Browse API item search
- marketplace header `X-EBAY-C-MARKETPLACE-ID: EBAY_GB`

Useful official eBay documentation:

- [Browse API overview](https://developer.ebay.com/api-docs/buy/browse/static/overview.html)
- [Using eBay RESTful APIs](https://developer.ebay.com/develop/guides-v2)

## Environment Variables

Required for live eBay searches:

```bash
export EBAY_CLIENT_ID="your-production-client-id"
export EBAY_CLIENT_SECRET="your-production-client-secret"
```

Optional Telegram notifications:

```bash
export TELEGRAM_BOT_TOKEN="123456:bot-token"
export TELEGRAM_CHAT_ID="123456789"
```

Telegram messages are sent only for unseen listings or meaningful price reductions that meet the configured alert score. Dry runs never send Telegram messages.

## Installation

From this folder:

```bash
cd /opt/git/AudioSalvageHunter
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

On a minimal Debian or Ubuntu install, install the Python packaging helpers first if `venv` or `pip` is missing:

```bash
sudo apt update
sudo apt install python3-venv python3-pip
```

You can also install it as a local package:

```bash
python -m pip install -e .
```

## Configuration

Edit `config.yaml`.

Important settings:

- `marketplace_id`: defaults to `EBAY_GB`
- `sqlite_path`: where seen listings are tracked
- `donor_database_path`: donor equipment CSV path
- `reports_dir`: where HTML and CSV reports are written
- `max_results_per_query`: Browse API results requested per search term
- `rate_limit_delay_seconds`: pause between eBay calls
- `minimum_alert_score`: threshold for normal display and notifications
- `meaningful_price_reduction_gbp`: minimum drop before a seen listing is notified again
- `collection_only_penalty`: score penalty for local pickup listings

Search terms live under:

- `search_groups.exact_equipment_models`
- `search_groups.component_names`
- `search_groups.generic_fault_descriptions`
- `search_groups.brand_plus_equipment_category`

Scoring phrases live under `scoring_terms`.

## Donor Database

Known donor equipment is stored in `donor_database.csv`.

Columns:

- `manufacturer`
- `model`
- `aliases`
- `category`
- `likely_valuable_components`
- `component_type`
- `confidence_level`
- `desirability_score`
- `maximum_worthwhile_delivered_price_gbp`
- `ideal_fault_types`
- `risky_fault_types`
- `salvage_difficulty`
- `package_or_removal_notes`
- `source_or_verification_note`
- `general_comments`

Use `|` or `;` to separate aliases, components, component types and fault phrases.

Allowed `confidence_level` values:

- `confirmed`: a model-specific component claim is supported by a credible review, service information, official document, or clearly labelled board evidence.
- `probable`: the model or family is strongly associated with the component class, but the exact board revision should still be checked.
- `uncertain`: the row is useful as a search target, but the exact component contents must be verified from internal photos, a service manual, or part markings.

The database is conservative by design. Rows can describe `DAC stage`, `ADC/DAC`, `op-amps`, `DSP`, `transformer`, or `power amp parts` without claiming an exact IC when the exact IC has not been verified. The terminal, HTML and CSV reports show donor confidence when a model matches.

The bundled database includes 175 UK-focused donor rows across PCI/PCIe sound cards, CD/SACD/DVD players, MiniDisc and DAT decks, studio interfaces, DACs, AV receivers, amplifiers, preamps, active speakers and rack audio equipment.

## Running

Mock-data test, with no eBay credentials, no eBay calls and no SQLite writes:

```bash
cd /opt/git/AudioSalvageHunter
python3 -m audio_salvage_hunter.cli --mock-data --show-all
```

`--dry-run` is kept as a compatibility alias:

```bash
python3 -m audio_salvage_hunter.cli --dry-run --show-all
```

Run the test suite:

```bash
python3 -m unittest discover -s tests
```

Live API test:

```bash
cd /opt/git/AudioSalvageHunter
export EBAY_CLIENT_ID="your-production-client-id"
export EBAY_CLIENT_SECRET="your-production-client-secret"
python3 -m audio_salvage_hunter.cli --show-all --no-telegram
```

Normal live run:

```bash
python3 -m audio_salvage_hunter.cli
```

HTML report generation:

```bash
python3 -m audio_salvage_hunter.cli --mock-data --show-all
xdg-open reports/audio_salvage_hunter_report.html
```

Telegram test, using mock data and no eBay call:

```bash
export TELEGRAM_BOT_TOKEN="123456:bot-token"
export TELEGRAM_CHAT_ID="123456789"
python3 -m audio_salvage_hunter.cli --telegram-test --show-all
```

Disable Telegram for one live run:

```bash
python3 -m audio_salvage_hunter.cli --no-telegram
```

If installed with `pip install -e .`, you can use:

```bash
audio-salvage-hunter --show-all
```

## Reports

Every run generates:

- terminal report
- `reports/audio_salvage_hunter_report.html`
- `reports/audio_salvage_hunter_report.csv`

Each listing includes:

- listing title
- item URL
- item price
- postage
- total delivered price
- price basis, such as item price or current auction bid
- buying options, such as auction, fixed price or best offer
- condition
- seller
- location
- image URL
- listing start/end time where eBay provides them
- score
- explanation of every score adjustment
- possible reusable components

## Seen Listing Tracking

The app stores seen eBay item IDs in SQLite.

It notifies only when:

- a listing has not been seen before, or
- the delivered price drops by at least `meaningful_price_reduction_gbp`

Listings are deduplicated by eBay item ID before scoring.

## Scoring

Scores are clamped from 0 to 100.

Default rules:

- exact or fuzzy donor model match: `+50`
- desirable component named: `+25`
- powers on: `+10`
- optical or mechanical fault: `+15`
- internal PCB photos likely present: `+10`
- price below configured maximum: `+10`
- water damage: `-25`
- burnt or smoke damage: `-30`
- reported no audio: `-20`
- missing boards or major parts: `-25`
- collection only: configurable penalty

The score explanation is part of both terminal and exported reports.

## Scheduling With Cron

Create a root-readable environment file, for example `/etc/audio-salvage-hunter.env`:

```bash
EBAY_CLIENT_ID=your-production-client-id
EBAY_CLIENT_SECRET=your-production-client-secret
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Example cron entry for a virtual environment in this folder:

```cron
*/30 * * * * set -a; . /etc/audio-salvage-hunter.env; set +a; cd /opt/git/AudioSalvageHunter && . .venv/bin/activate && python -m audio_salvage_hunter.cli >> audio_salvage_hunter.log 2>&1
```

Keep the environment file outside git and restrict it to the user that runs the job.

## Scheduling With systemd

Example service unit:

```ini
[Unit]
Description=Audio Salvage Hunter

[Service]
Type=oneshot
WorkingDirectory=/opt/git/AudioSalvageHunter
EnvironmentFile=/etc/audio-salvage-hunter.env
ExecStart=/opt/git/AudioSalvageHunter/.venv/bin/python -m audio_salvage_hunter.cli
```

Example timer:

```ini
[Unit]
Description=Run Audio Salvage Hunter every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
```

Save them as:

- `/etc/systemd/system/audio-salvage-hunter.service`
- `/etc/systemd/system/audio-salvage-hunter.timer`

Then enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now audio-salvage-hunter.timer
```

For real deployments, prefer `EnvironmentFile=` pointing to a root-readable secrets file instead of putting API credentials directly in the unit.

## Tests

Run:

```bash
cd /opt/git/AudioSalvageHunter
python3 -m unittest discover -s tests
```

If you have installed the development dependencies, this also works:

```bash
python -m pytest
```

The tests cover matching, scoring, eBay response parsing, total-price calculation, duplicate handling, price-drop detection, notification repeat prevention, SQLite preservation, and malformed configuration files.

## Web Architecture

The web application wraps the existing scanner rather than replacing it.

- Backend: FastAPI
- Pages: Jinja2 server-rendered templates
- Styling: Bootstrap CDN
- Database: SQLite through SQLAlchemy
- Migrations: Alembic
- Scheduler: APScheduler
- Deployment: Docker Compose

The web database stores listings, price history, scan runs, scan errors, donor entries, search terms and user-visible settings. Existing `donor_database.csv` data is imported into SQLite on first startup. Existing legacy seen-listing SQLite data is imported if `audio_salvage_hunter.sqlite3` exists.

Secrets still come only from environment variables. They are never written to the settings table or config files.

## Docker Installation

Copy the environment template:

```bash
cd /opt/git/AudioSalvageHunter
cp .env.example .env
```

Edit `.env` and set at least:

```bash
APP_SECRET_KEY=replace-with-a-long-random-value
```

For live eBay scans, also set:

```bash
EBAY_CLIENT_ID=your-production-client-id
EBAY_CLIENT_SECRET=your-production-client-secret
```

For Telegram notifications, set:

```bash
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

Build the image:

```bash
docker compose build
```

Start the stack:

```bash
docker compose up -d
```

Open:

```text
http://localhost:8085
```

## Scheduled Scanning In Docker

Scheduled scans are controlled from the web Settings page.

1. Open `http://localhost:8085/settings`.
2. Tick `Enable scheduled scans`.
3. Set `Scan interval minutes`.
4. Leave `Use mock data` ticked while you do not have eBay API credentials.
5. Click `Save settings`.

The dashboard shows the next scheduled scan time and whether the scheduler will run in `mock` or `live` mode.

When `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` are not configured, scheduled scans automatically use mock data so the app does not repeatedly fail unattended. After adding eBay credentials to `.env`, turn `Use mock data` off and restart the stack:

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f
```

Stop the stack:

```bash
docker compose down
```

## First Login

Login is optional. Enable it in `.env`:

```bash
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=sha256-password-hash
```

Generate a simple SHA-256 password hash:

```bash
python3 -c "import hashlib,getpass; print('sha256$'+hashlib.sha256(getpass.getpass().encode()).hexdigest())"
```

Set `COOKIE_SECURE=true` only when serving behind HTTPS.

## Persistent Volumes

Docker Compose uses named persistent volumes:

- `ash_data` for SQLite
- `./config.yaml` mounted read-only as the container config
- `ash_reports` for reports
- `ash_logs` for application logs
- `ash_exports` for CSV exports

Edit `config.yaml` in the project root when you want to change the mounted configuration.

## Migrations

Migrations run automatically on container startup.

Run them manually:

```bash
docker compose run --rm audio-salvage-hunter alembic upgrade head
```

Check migration status:

```bash
docker compose run --rm audio-salvage-hunter alembic current
```

## Mock Mode

Mock mode needs no eBay credentials:

```bash
docker compose up -d
curl -X POST http://localhost:8085/api/scans \
  -H "Content-Type: application/json" \
  -d '{"mode":"mock","notifications_enabled":false}'
```

Or use the browser:

```text
http://localhost:8085/scan
```

## Running Tests

Local pure-Python tests:

```bash
python3 -m unittest discover -s tests
```

Full test suite inside Docker:

```bash
docker compose build
docker run --rm --entrypoint python audiosalvagehunter-audio-salvage-hunter:latest -m unittest discover -s tests
```

The tests use mock scans and mocked/local storage. They do not require live eBay credentials.

## Backup And Restore

Back up the persistent data:

```bash
mkdir -p backups
docker run --rm \
  -v audiosalvagehunter_ash_data:/data \
  -v "$PWD/backups:/backup" \
  alpine tar -czf /backup/audio-salvage-hunter-data-$(date +%Y%m%d-%H%M%S).tar.gz -C /data .
```

Restore a backup:

```bash
docker compose down
docker run --rm \
  -v audiosalvagehunter_ash_data:/data \
  -v "$PWD/backups:/backup" \
  alpine sh -c "rm -rf /data/* && tar -xzf /backup/audio-salvage-hunter-data-YYYYMMDD-HHMMSS.tar.gz -C /data"
docker compose up -d
```

For an SQLite-only backup:

```bash
docker compose exec audio-salvage-hunter python -c "import sqlite3; src=sqlite3.connect('/app/data/audio_salvage_hunter.sqlite3'); dst=sqlite3.connect('/app/data/audio_salvage_hunter-backup.sqlite3'); src.backup(dst)"
```

## Upgrading

Pull or apply the new code, then run:

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

The container runs Alembic migrations on startup.

## Troubleshooting

Health checks:

```bash
curl http://localhost:8085/health
curl http://localhost:8085/health/ready
```

Recent app logs:

```bash
docker compose logs --tail=200 audio-salvage-hunter
```

If live scans fail, confirm the eBay secrets are present:

```bash
docker compose exec audio-salvage-hunter python -c "import os; print(bool(os.getenv('EBAY_CLIENT_ID')), bool(os.getenv('EBAY_CLIENT_SECRET')))"
```

Do not print the actual secret values.

## Security Notes

- The app is intended for a single-user home server.
- Enable `AUTH_ENABLED=true` if the service is reachable by anyone else.
- Use a long random `APP_SECRET_KEY`.
- Put the service behind HTTPS before setting `COOKIE_SECURE=true`.
- The web app does not expose raw SQLite files.
- Forms use CSRF tokens.
- The app does not allow arbitrary shell commands or arbitrary filesystem paths.
- Buying, bidding, seller messaging and watchlist automation are intentionally absent.
