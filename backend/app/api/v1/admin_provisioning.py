"""Administrator-only provisioning against the fictional local roster."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.auth import _COOKIE_AUTH_GUARDS, _NO_STORE, read_auth_json
from app.core.config import settings
from app.database.session import get_session_factory
from app.dependencies.auth import require_roles
from app.models.enums import UserRole
from app.schemas.provisioning import (
    DemoRosterResponse, ProvisioningResponse, StudentProvisioningRequest, TutorProvisioningRequest,
)
from app.services.account_provisioning import (
    AccountProvisioningService, InvitationDeliveryError, ProvisioningConflictError, ProvisioningValidationError,
)
from app.services.demo_accounts import DEMO_STUDENT, DEMO_TUTOR, DemoInvitationOutbox


async def local_demo_directory(request: Request) -> Path:
    if (
        settings.ENVIRONMENT != "local-demo"
        or settings.LOCAL_DEMO_DIR is None
        or request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
    ):
        raise HTTPException(404, "Local demo provisioning is unavailable.", headers=_NO_STORE)
    return settings.LOCAL_DEMO_DIR


_admin = APIRouter(prefix="/admin", tags=["Local demo administration"],
                   dependencies=[Depends(require_roles(UserRole.ADMIN))])
DemoDirectory = Annotated[Path, Depends(local_demo_directory)]


@_admin.get("/demo-roster", response_model=DemoRosterResponse, dependencies=[Depends(local_demo_directory)])
async def demo_roster(response: Response) -> DemoRosterResponse:
    response.headers.update(_NO_STORE)
    return DemoRosterResponse(students=[DEMO_STUDENT], tutors=[DEMO_TUTOR])


def _provision(directory: Path, request: StudentProvisioningRequest | TutorProvisioningRequest) -> ProvisioningResponse:
    try:
        service = AccountProvisioningService(
            session_factory=get_session_factory(), deliver_invitation=DemoInvitationOutbox(directory),
        )
        if isinstance(request, StudentProvisioningRequest):
            account = service.provision_student(request, approved=DEMO_STUDENT)
        else:
            account = service.provision_tutor(request, approved=DEMO_TUTOR)
        delivered = True
    except InvitationDeliveryError as error:
        account = error.account
        delivered = False
    except ProvisioningValidationError:
        raise HTTPException(400, "Account details do not match the approved demo roster.", headers=_NO_STORE) from None
    except ProvisioningConflictError:
        raise HTTPException(409, "An account with those details already exists.", headers=_NO_STORE) from None
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        raise HTTPException(503, "Account provisioning is unavailable.", headers=_NO_STORE) from None
    return ProvisioningResponse(
        user_id=account.user_id, profile_id=account.profile_id, invitation_id=account.invitation_id,
        invitation_delivered=delivered,
    )


@_admin.post("/students", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def provision_student(request: Request, response: Response, directory: DemoDirectory) -> ProvisioningResponse:
    data = await read_auth_json(request, StudentProvisioningRequest)
    if data is None:
        raise HTTPException(400, "Invalid student provisioning request.", headers=_NO_STORE)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_provision, directory, data)


@_admin.post("/tutors", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def provision_tutor(request: Request, response: Response, directory: DemoDirectory) -> ProvisioningResponse:
    data = await read_auth_json(request, TutorProvisioningRequest)
    if data is None:
        raise HTTPException(400, "Invalid tutor provisioning request.", headers=_NO_STORE)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_provision, directory, data)


admin_provisioning_router = _admin
