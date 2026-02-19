FROM python:3.14-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (cache layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Collect static files
RUN uv run python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "uv run manage.py migrate --noinput && uv run gunicorn reader.wsgi:application --bind 0.0.0.0:8000 --workers 2"]
