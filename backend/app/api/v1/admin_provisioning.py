"""Administrator-only provisioning against the fictional local roster."""

from pathlib import Path
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.v1.auth import _COOKIE_AUTH_GUARDS, _NO_STORE, read_auth_json
from app.core.config import settings
from app.database.session import get_session_factory
from app.dependencies.auth import AuthenticatedUser, require_roles
from app.models.enums import UserRole
from app.schemas.provisioning import (
    ApprovedHODRecord, ApprovedStudentRecord, ApprovedTutorRecord,
    DemoRosterResponse, HODProvisioningRequest, ProvisioningResponse, StudentProvisioningRequest, TutorProvisioningRequest,
)
from app.services.account_provisioning import (
    AccountProvisioningService, InvitationDeliveryError, ProvisioningConflictError, ProvisioningValidationError,
)
from app.services.demo_accounts import DEMO_HOD, DEMO_STUDENT, DEMO_TUTOR, DemoInvitationOutbox
from app.models.academic import Class
from app.schemas.admin import AdminInvite


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
Admin = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.ADMIN))]


@_admin.get("/demo-roster", response_model=DemoRosterResponse, dependencies=[Depends(local_demo_directory)])
async def demo_roster(response: Response) -> DemoRosterResponse:
    response.headers.update(_NO_STORE)
    return DemoRosterResponse(students=[DEMO_STUDENT], tutors=[DEMO_TUTOR], hods=[DEMO_HOD])


def _provision(
    directory: Path, request: StudentProvisioningRequest | TutorProvisioningRequest | HODProvisioningRequest | AdminInvite,
    administrator_id: UUID, *, manual: bool = False,
) -> ProvisioningResponse:
    try:
        service = AccountProvisioningService(
            session_factory=get_session_factory(), deliver_invitation=DemoInvitationOutbox(directory),
        )
        if isinstance(request, AdminInvite):
            account = service.provision_admin(request, actor_id=administrator_id)
        elif isinstance(request, StudentProvisioningRequest):
            approved = DEMO_STUDENT
            if manual:
                with get_session_factory()() as db:
                    item = db.get(Class, request.class_id)
                    if item is None:
                        raise ProvisioningValidationError()
                    approved = ApprovedStudentRecord(**request.model_dump(), academic_year_id=item.academic_year_id)
            account = service.provision_student(request, approved=approved, actor_id=administrator_id)
        elif isinstance(request, TutorProvisioningRequest):
            approved = ApprovedTutorRecord(**request.model_dump()) if manual else DEMO_TUTOR
            account = service.provision_tutor(request, approved=approved, actor_id=administrator_id)
        else:
            approved = ApprovedHODRecord(**request.model_dump()) if manual else DEMO_HOD
            account = service.provision_hod(request, approved=approved, administrator_id=administrator_id)
        delivered = True
    except InvitationDeliveryError as error:
        account = error.account
        delivered = False
    except ProvisioningValidationError:
        message = "Check the account details and academic references." if manual else "Account details do not match the approved demo roster."
        raise HTTPException(400, message, headers=_NO_STORE) from None
    except ProvisioningConflictError:
        raise HTTPException(409, "An account with those details already exists.", headers=_NO_STORE) from None
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        raise HTTPException(503, "Account provisioning is unavailable.", headers=_NO_STORE) from None
    return ProvisioningResponse(
        user_id=account.user_id, profile_id=account.profile_id, invitation_id=account.invitation_id,
        invitation_delivered=delivered,
    )


@_admin.post("/students", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def provision_student(request: Request, response: Response, directory: DemoDirectory, admin: Admin) -> ProvisioningResponse:
    data = await read_auth_json(request, StudentProvisioningRequest)
    if data is None:
        raise HTTPException(400, "Invalid student provisioning request.", headers=_NO_STORE)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_provision, directory, data, admin.user_id)


@_admin.post("/tutors", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def provision_tutor(request: Request, response: Response, directory: DemoDirectory, admin: Admin) -> ProvisioningResponse:
    data = await read_auth_json(request, TutorProvisioningRequest)
    if data is None:
        raise HTTPException(400, "Invalid tutor provisioning request.", headers=_NO_STORE)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_provision, directory, data, admin.user_id)


@_admin.post("/hods", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def provision_hod(request: Request, response: Response, directory: DemoDirectory, admin: Admin) -> ProvisioningResponse:
    data = await read_auth_json(request, HODProvisioningRequest)
    if data is None:
        raise HTTPException(400, "Invalid HOD provisioning request.", headers=_NO_STORE)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_provision, directory, data, admin.user_id)


@_admin.post("/accounts/{kind}", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def provision_manual(kind: str, request: Request, response: Response, directory: DemoDirectory,
                           admin: Admin) -> ProvisioningResponse:
    schema = {"student": StudentProvisioningRequest, "faculty": TutorProvisioningRequest,
              "hod": HODProvisioningRequest, "admin": AdminInvite}.get(kind)
    if schema is None:
        raise HTTPException(404, "Unknown account type.", headers=_NO_STORE)
    data = await read_auth_json(request, schema)
    if data is None:
        raise HTTPException(422, "Check the required account fields.", headers=_NO_STORE)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_provision, directory, data, admin.user_id, manual=True)


admin_provisioning_router = _admin
