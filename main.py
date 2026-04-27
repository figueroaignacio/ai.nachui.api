from fastapi import FastAPI

app = FastAPI(title="UTN Buddy API")


@app.get("/health")
async def health():
    return {"status": "ok"}
