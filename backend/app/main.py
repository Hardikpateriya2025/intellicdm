from fastapi import FastAPI

from app.encounters import router as encounters_router
from app.labs import router as labs_router
from app.patients import router as patients_router

app = FastAPI(
    title="IntelliCDM API",
    version="0.1.0",
    description="Clinical Data Management and Intelligence System",
)

from fastapi import Depends
from app.auth import (
    router as auth_router,
    clinical_access,
    analysis_access,
    review_access,
)

app.include_router(patients_router, dependencies=[Depends(clinical_access)])
app.include_router(encounters_router, dependencies=[Depends(clinical_access)])
app.include_router(labs_router, dependencies=[Depends(clinical_access)])

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "IntelliCDM"}


from app.ml import router as ml_router
app.include_router(ml_router, dependencies=[Depends(analysis_access)])

from app.reviews import router as reviews_router
app.include_router(reviews_router, dependencies=[Depends(review_access)])

from app.ai import router as ai_router
app.include_router(ai_router, dependencies=[Depends(analysis_access)])

from app.questions import router as questions_router
app.include_router(questions_router, dependencies=[Depends(analysis_access)])

from app.trends import router as trends_router
app.include_router(trends_router, dependencies=[Depends(analysis_access)])

from app.review_queue import router as review_queue_router
app.include_router(review_queue_router, dependencies=[Depends(analysis_access)])

app.include_router(auth_router)

from app.users import router as users_router
app.include_router(users_router)

from app.semantic_search import router as semantic_search_router
app.include_router(semantic_search_router)
from app.agent import router as agent_router
app.include_router(agent_router)


from app.dashboard import router as dashboard_router
app.include_router(dashboard_router)

from app.panels import router as panels_router
app.include_router(panels_router)


from app.score_snapshot import router as score_snapshot_router
app.include_router(score_snapshot_router)

from app.csv_analysis import router as csv_analysis_router
app.include_router(csv_analysis_router)

from app.csv_records import router as csv_records_router
app.include_router(csv_records_router)
