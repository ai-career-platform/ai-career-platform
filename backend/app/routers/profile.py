from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.core.profile_problems import ProfileProblem, ProfileRoute
from app.dependencies.profile import AuthenticatedUser, get_authenticated_user, get_profile_repository
from app.repositories.profile import ProfileRepository
from app.schemas.profile import Me, MePatch
from app.services.profile import ProfileService

router = APIRouter(route_class=ProfileRoute, tags=["me"])
User = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
Repository = Annotated[ProfileRepository, Depends(get_profile_repository)]
PROBLEM_SCHEMA = {
    "type": "object", "required": ["type", "title", "status", "code", "request_id"],
    "properties": {
        "type": {"type": "string", "format": "uri"}, "title": {"type": "string"},
        "status": {"type": "integer"}, "code": {"type": "string"},
        "request_id": {"type": "string"},
        "errors": {"type": "array", "items": {"type": "object", "required": ["field", "code"],
                    "properties": {"field": {"type": "string"}, "code": {"type": "string"}}}},
    },
}
ERRORS = {status: {"description": description,
                  "content": {"application/problem+json": {"schema": PROBLEM_SCHEMA}}} for status, description in
          [(401, "Authentication required"), (404, "Profile not found"),
           (422, "Validation failed"), (503, "Dependency unavailable")]}


def private_request(request: Request, response: Response) -> None:
    if request.query_params:
        raise ProfileProblem(422, "VALIDATION_FAILED", "Query parameters are not supported")
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=Me, operation_id="getMe", responses=ERRORS)
def get_me(request: Request, response: Response, user: User, repository: Repository) -> Me:
    private_request(request, response)
    return ProfileService(repository).get(user.user_id)


@router.patch("/me", response_model=Me, operation_id="updateMe", responses=ERRORS)
def patch_me(request: Request, response: Response, patch: MePatch, user: User,
             repository: Repository) -> Me:
    private_request(request, response)
    return ProfileService(repository).patch(user.user_id, patch)
