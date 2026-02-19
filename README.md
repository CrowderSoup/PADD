# PADD — Personal Aggregation Display Dashboard

A self-hosted [IndieWeb](https://indieweb.org/) feed reader built with Django. PADD connects to your personal website's [Microsub](https://indieweb.org/Microsub) endpoint and lets you read, interact with, and publish content — all from one place.

## Features

- **Read** your feeds organized into channels via Microsub
- **Publish** notes, articles, photos, and check-in posts via [Micropub](https://indieweb.org/Micropub)
- **Interact** with posts — like, repost, and reply — through your Micropub endpoint
- **Authenticate** with your personal domain using [IndieAuth](https://indieweb.org/IndieAuth) (PKCE flow)
- **PWA-ready** with a service worker for offline support and installability
- LCARS-themed UI (yes, like Star Trek)

## Requirements

- Python 3.14+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/) for dependency management
- A personal website with IndieAuth and Microsub endpoints (e.g. powered by [Aperture](https://aperture.p3k.io/))

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/CrowderSoup/PADD.git
cd PADD
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your settings. At minimum you need a secret key and a database URL.

### 3. Set up the database

```bash
uv run manage.py migrate
```

### 4. Run the development server

```bash
uv run manage.py runserver
```

Visit `http://localhost:8000` and log in with your personal domain.

## Environment Variables

| Variable                      | Required | Default                                    | Description                                                                                                              |
| ----------------------------- | -------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| `DJANGO_SECRET_KEY`           | Yes      | `change-me-in-production`                  | Django secret key. Use a long random string in production.                                                               |
| `DJANGO_DEBUG`                | No       | `False`                                    | Set to `True` for local development. Never enable in production.                                                         |
| `DJANGO_ALLOWED_HOSTS`        | No       | `localhost,127.0.0.1`                      | Comma-separated list of allowed hostnames.                                                                               |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | No       | _(empty)_                                  | Comma-separated list of trusted origins for CSRF (e.g. `https://yourdomain.com`). Required in production behind a proxy. |
| `DATABASE_URL`                | No       | `postgres://padd:padd@localhost:5432/padd` | PostgreSQL connection URL.                                                                                               |
| `PADD_ADMIN_URLS`             | No       | _(empty)_                                  | Comma-separated list of user URLs with admin access (e.g. `https://yourdomain.com/`).                                    |

## Docker

A `docker-compose.yml` is provided for production and a `docker-compose.dev.yml` for local development with Caddy as a reverse proxy.

### Production

```bash
docker compose up -d
```

### Development (with Caddy + HTTPS)

```bash
docker compose -f docker-compose.dev.yml up
```

The dev setup uses Caddy for automatic TLS, which is useful for testing IndieAuth flows that require HTTPS.

## Running Tests

```bash
uv run manage.py test
```

## Architecture

```
reader/               Django project settings and root URL config
microsub_client/      Main application
  api.py              Microsub protocol client
  auth.py             IndieAuth / PKCE helpers
  micropub.py         Micropub protocol client
  middleware.py       Session-based authentication middleware
  models.py           Database models
  views.py            View functions
  utils.py            HTML sanitization and formatting helpers
  templates/          Django templates (base + partials)
  static/             CSS, JS modules, service worker, PWA manifest
```

## Protocol Support

PADD implements the following IndieWeb protocols as a **client**:

- [IndieAuth](https://indieauth.spec.indieweb.org/) — authentication via your personal domain
- [Microsub](https://indieweb.org/Microsub) — reading feeds from a Microsub server
- [Micropub](https://micropub.spec.indieweb.org/) — publishing posts to your site

PADD does **not** include a Microsub server. You'll need a separate server such as [Aperture](https://aperture.p3k.io/) or [Ekster](https://indieweb.org/Ekster) configured on your personal site.

## License

MIT — see [LICENSE](LICENSE).
