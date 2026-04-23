# D-SCO Bluesky Battle Report Bot

Automatically posts Fraternity. battle report wins to Bluesky with smirky propaganda comments.

## How it works

1. Polls `br.evetools.org/api/v1/recent-br` every 10 minutes
2. Filters for battles where Fraternity. (alliance ID 99003581) participated
3. Checks if Fraternity's side won (ISK efficiency > 55%)
4. Generates a smirky comment and posts to Bluesky with a link to the BR

## Setup

### 1. Create a Bluesky App Password

Go to **Bluesky Settings → App Passwords → Add App Password** and create one for the bot.

### 2. Configure

Edit `docker-compose.yml` and set your `BLUESKY_HANDLE`:

```yaml
environment:
  - BLUESKY_HANDLE=# your actual handle
  - BLUESKY_APP_PASSWORD=
```

### 3. Deploy

Copy the project to your server and run:

```bash
docker compose up -d
```

Check logs:

```bash
docker compose logs -f
```

### 4. Test (dry run)

Run the bot outside Docker to test:

```bash
pip install requests
BLUESKY_HANDLE= \
BLUESKY_APP_PASSWORD= \
LOG_LEVEL=DEBUG \
python bot.py
```

## Configuration

| Variable               | Default    | Description                  |
| ---------------------- | ---------- | ---------------------------- |
| `BLUESKY_HANDLE`       | (required) | Your Bluesky handle          |
| `BLUESKY_APP_PASSWORD` | (required) | Bluesky app password         |
| `POLL_INTERVAL`        | 600        | Seconds between API polls    |
| `MIN_PILOTS`           | 20         | Minimum pilots in BR to post |
| `MIN_ISK_DESTROYED`    | 500000000  | Minimum ISK destroyed (500M) |
| `MIN_EFFICIENCY`       | 55         | Minimum ISK efficiency %     |
| `LOG_LEVEL`            | INFO       | Logging verbosity            |

## Customizing Comments

Edit the `SMIRKY_TEMPLATES` list in `bot.py` to add/change the propaganda lines.

Available template variables:

- `{system}` — system name (e.g. O-VWPB)
- `{efficiency}` — ISK efficiency % (e.g. 67.2)
- `{isk_destroyed}` — ISK destroyed formatted (e.g. 41.1B)
- `{isk_lost}` — ISK lost formatted (e.g. 32.6B)
- `{pilots}` — total pilots in the fight

## Adding Friendly Alliances

If new alliances join the Fraternity coalition, add their IDs to the
`FRIENDLY_ALLIANCES` set in `bot.py`. This set is reserved for future use
if you want to filter BRs where coalition members are present but Frat isn't
the main force.
