"""Health endpoint: a cheap way for a person, the frontend or a host to check the server is up."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
