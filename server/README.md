# Fog Gate Tracker - Backend Server

FastAPI backend server with PostgreSQL, Twitch OAuth, and WebSocket sync.

## Development Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 15+

### Installation

```bash
cd server

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Configuration

Create a `.env` file:

```bash
cp .env.example .env
# Edit .env with your values
```

Required environment variables:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/fogtracker
TWITCH_CLIENT_ID=your_twitch_client_id
TWITCH_CLIENT_SECRET=your_twitch_client_secret
TWITCH_REDIRECT_URI=http://localhost:8001/auth/twitch/callback
SECRET_KEY=your_random_secret_key
```

### Database Setup

```bash
# Create database
createdb fogtracker

# Run migrations
alembic upgrade head
```

### Running

```bash
# Development (with auto-reload)
uvicorn fogtracker.main:app --reload --port 8001

# Or using the entry point
fogtracker
```

The server runs at http://localhost:8001

### Linting

```bash
# Run pre-commit on all files
pre-commit run --all-files

# Or run ruff directly
ruff check .
ruff format .
```

### Testing

```bash
pytest
```

## Production Deployment

### Systemd Service

```bash
# Copy service file
sudo cp fog-tracker.service /etc/systemd/system/

# Edit paths if needed
sudo systemctl edit fog-tracker

# Enable and start
sudo systemctl enable fog-tracker
sudo systemctl start fog-tracker

# Check status
sudo systemctl status fog-tracker
journalctl -u fog-tracker -f
```

### Nginx

Add to your nginx server block:

```bash
# Option 1: Include the config file
include /var/www/fog-tracker/server/fog-tracker.nginx.conf;

# Option 2: Copy content to your site config
sudo nano /etc/nginx/sites-available/your-site
```

Then reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### Production Checklist

- [ ] Set strong `SECRET_KEY` in `.env`
- [ ] Configure `CORS_ORIGINS` for your domain
- [ ] Set up PostgreSQL with proper credentials
- [ ] Configure Twitch OAuth with production redirect URI
- [ ] Enable HTTPS in nginx
- [ ] Set appropriate file permissions (`chown www-data:www-data`)

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## Project Structure

```
server/
├── fogtracker/
│   ├── __init__.py
│   ├── main.py            # FastAPI app entry point
│   ├── config.py          # Settings (pydantic-settings)
│   ├── database.py        # SQLAlchemy models
│   ├── models.py          # Pydantic schemas
│   ├── auth.py            # Twitch OAuth
│   ├── game_logic.py      # Discovery propagation
│   ├── websocket.py       # WebSocket handlers
│   ├── zone_matching.py   # Match mod coordinates to zone names
│   ├── zone_resolver.py   # Resolve zones to graph node IDs
│   └── api/
│       ├── __init__.py
│       ├── auth.py        # /auth/* routes
│       ├── users.py       # /api/users/* routes
│       └── games.py       # /api/games/* routes
├── alembic/               # Database migrations
├── data/                  # Static data files (zone coordinates)
├── pyproject.toml
├── .env.example
├── fog-tracker.service       # Systemd unit
└── fog-tracker.nginx.conf    # Nginx config
```
