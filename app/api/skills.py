from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.models import SkillRecord

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillToggleRequest(BaseModel):
    enabled: bool


@router.get("", response_model=list[SkillRecord])
def list_skills(
    container: ApplicationContainer = Depends(get_container),
) -> list[SkillRecord]:
    return container.skills.discover()


@router.patch("/{name}", response_model=SkillRecord)
def toggle_skill(
    name: str,
    payload: SkillToggleRequest,
    container: ApplicationContainer = Depends(get_container),
) -> SkillRecord:
    try:
        return container.skills.set_enabled(name, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill 未安装") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
