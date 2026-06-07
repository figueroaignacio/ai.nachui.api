# UI Generator API

A modern backend API for generating and managing user interface components, built with Python, FastAPI, and managed with `uv`.

## Features

- **FastAPI**: Modern, fast (high-performance) web framework.
- **uv**: Fast Python package installer and resolver.
- **Interactive Documentation**: Available out of the box via Swagger UI and ReDoc.
- **CORS Support**: Configured to allow cross-origin requests.

## Getting Started

### Prerequisites

- Python 3.12 or newer.
- [uv](https://github.com/astral-sh/uv) installed on your system.

### Installation

No manual virtualenv creation or pip install is required. `uv` handles dependency management and running the app seamlessly.

To verify dependencies and lock files, you can run:

```bash
uv sync
```

### Running the Application

Start the development server with hot-reloading:

```bash
uv run uvicorn main:app --reload
```

The application will be available at [http://127.0.0.1:8000](http://127.0.0.1:8000).

### API Documentation

Once the server is running, you can explore and interact with the API endpoints through the following documentation pages:

- **Swagger UI (Interactive)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

## Project Structure

- `main.py` - Core entry point containing endpoints and middleware config.
- `pyproject.toml` - Project configuration and dependencies.
- `uv.lock` - Dependency lock file.
