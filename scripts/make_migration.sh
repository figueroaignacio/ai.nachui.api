#!/bin/bash
# Create a new database migration automatically by comparing models to the DB
if [ -z "$1" ]; then
    echo "Usage: ./scripts/make_migration.sh \"Migration message here\""
    exit 1
fi
uv run alembic revision --autogenerate -m "$1"
