#!/bin/bash
# Run the FastAPI server in development mode with live reloading
uv run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
