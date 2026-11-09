from typing import Annotated
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.repositories.career_history import CareerHistoryRepository, SqlCareerHistoryRepository

def get_career_history_repository(db: Annotated[Session, Depends(get_db)]) -> CareerHistoryRepository:
    return SqlCareerHistoryRepository(db)
