# D-SCO Bluesky Battle Report Bot

Automatically posts Fraternity. battle report wins to Bluesky with smirky propaganda comments.

## How it works

1. Polls `br.evetools.org/api/v1/recent-br` every 10 minutes
2. Filters for battles where Fraternity. (alliance `99003581`) or D-SCO (corp `98519746`) participated
3. Requires at least 10 FRT pilots present and 20+ total pilots in the fight
4. Fetches per-team ISK from the composition endpoint — only posts if FRT's side destroyed more ISK than they lost
5. Generates a smirky comment and posts to Bluesky with a link to the BR
6. Deduplicates via MariaDB so the same BR is never posted twice

## Setup

### 1. Create a Bluesky App Password

Go to **Bluesky Settings → App Passwords → Add App Password** and create one for the bot.

### 2. Configure

Copy `.env.example` to `.env` (or set environment variables directly) and fill in the required values.

### 3. Deploy

```bash
docker compose up -d
```

Check logs:

```bash
docker compose logs -f
```

### 4. Test (dry run)

```bash
pip install requests pymysql
BLUESKY_HANDLE=you.bsky.social \
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx \
DB_HOST=localhost DB_USER=dsco DB_PASSWORD=secret DB_NAME=dsco_bot \
LOG_LEVEL=DEBUG \
python bot.py
```

## Configuration

### Required

| Variable               | Description                                    |
| ---------------------- | ---------------------------------------------- |
| `BLUESKY_HANDLE`       | Your Bluesky handle (e.g. `dsco.bsky.social`)  |
| `BLUESKY_APP_PASSWORD` | Bluesky app password                           |
| `DB_USER`              | MariaDB username                               |
| `DB_PASSWORD`          | MariaDB password                               |

### Optional

| Variable            | Default     | Description                                                  |
| ------------------- | ----------- | ------------------------------------------------------------ |
| `DB_HOST`           | `localhost` | MariaDB host                                                 |
| `DB_PORT`           | `3306`      | MariaDB port                                                 |
| `DB_NAME`           | `dsco_bot`  | MariaDB database name                                        |
| `POLL_INTERVAL`     | `600`       | Seconds between API polls                                    |
| `MIN_PILOTS`        | `20`        | Minimum total pilots in BR to consider                       |
| `MIN_FRT_PILOTS`    | `10`        | Minimum FRT pilots that must be present in the BR            |
| `MIN_ISK_DESTROYED` | `500000000` | Minimum ISK destroyed (enemy side) to post — default 500M   |
| `LOG_LEVEL`         | `INFO`      | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`)      |

## Customizing Comments

Edit the `SMIRKY_TEMPLATES` list in `bot.py` to add or change the propaganda lines.

Available template variables:

| Variable          | Example   | Description                         |
| ----------------- | --------- | ----------------------------------- |
| `{system}`        | `O-VWPB`  | Solar system name                   |
| `{efficiency}`    | `67.2`    | FRT ISK efficiency %                |
| `{isk_destroyed}` | `41.1B`   | Enemy ISK destroyed (formatted)     |
| `{isk_lost}`      | `12.6B`   | FRT ISK lost (formatted)            |
| `{pilots}`        | `214`     | Total pilots in the fight           |

Templates containing `{efficiency}` are automatically excluded when efficiency data is unavailable.
