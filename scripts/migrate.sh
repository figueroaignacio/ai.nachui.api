#!/bin/bash
# Apply all pending migrations to the database
uv run alembic upgrade head
