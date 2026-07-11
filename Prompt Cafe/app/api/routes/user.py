from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.db import models
from app.schemas.user import UpdateMyProfileRequest, UserResponse


router = APIRouter()


@router.get("/me", response_model=UserResponse, summary="Get my profile")
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    return {
        "code": 0,
        "message": "success",
        "data": current_user,
    }


@router.put("/me", response_model=UserResponse, summary="Update my profile")
def update_my_profile(
    request: UpdateMyProfileRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    update_data = request.model_dump(exclude_unset=True, by_alias=False)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one editable field must be provided",
        )

    for field_name in ("nickname", "avatar_url", "bio"):
        if field_name in update_data:
            setattr(current_user, field_name, update_data[field_name])

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return {
        "code": 0,
        "message": "success",
        "data": current_user,
    }
