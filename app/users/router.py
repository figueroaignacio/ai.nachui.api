from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.users.models import User
from app.users.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user",
    description="Returns the profile of the currently authenticated user. "
    "Requires a valid Bearer access token.",
)
async def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
