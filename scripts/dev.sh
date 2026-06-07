#!/bin/bash
# Run the FastAPI server in development mode with live reloading
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
