from fastapi import FastAPI

from app.patients import router as patients_router

app = FastAPI(
    title="IntelliCDM API",
    version="0.1.0",
    description="Clinical Data Management and Intelligence System",
)

app.include_router(patients_router)

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "IntelliCDM"}
