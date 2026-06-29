from sqlalchemy import text
from sqlalchemy.orm import Session


def database_ready(session: Session) -> bool:
    session.execute(text("SELECT 1"))
    return True
