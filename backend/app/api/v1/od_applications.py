"""OD endpoints for owning students and assigned tutors."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import PurePath
from typing import Annotated, Literal, TypeVar
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from python_multipart.exceptions import MultipartParseError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from app.api.v1.auth import read_auth_json
from app.core.config import settings
from app.database.session import get_session_factory
from app.dependencies.auth import AuthenticatedUser, require_roles
from app.models.enums import DocumentType, UserRole
from app.schemas.application import ApplicationCorrection, ApplicationDetail, ApplicationSubmission, ApplicationSummary, TutorDecision
from app.schemas.evidence import ApplicationEvidenceView, DayEvidenceDecision, EvidenceUploadRequest
from app.services.od_applications import ODApplicationService, ODFile
from app.services.od_evidence import ODEvidenceService
from app.services.private_uploads import ApplicationError, PrivateUpload
from app.services.storage import storage_service

od_router = APIRouter(tags=["On-Duty applications"])
Student = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.STUDENT))]
Tutor = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.TUTOR))]
Participant = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.STUDENT, UserRole.TUTOR))]
_Result = TypeVar("_Result")
_Service = TypeVar("_Service", ODApplicationService, ODEvidenceService)
_NO_STORE = {"Cache-Control": "no-store"}
_FIELDS = {
    "original_form": DocumentType.ORIGINAL_SIGNED_OD_FORM,
    "event_invitation": DocumentType.EVENT_INVITATION,
    "parent_consent": DocumentType.PARENT_CONSENT,
}
_FILE_TYPES = {
    ".pdf": ("application/pdf", b"%PDF-", b"%%EOF"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n", b"IEND\xaeB\x60\x82"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff", b"\xff\xd9"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff", b"\xff\xd9"),
}


def _error(status: int, message: str) -> HTTPException:
    return HTTPException(status, message, headers=_NO_STORE)


def _perform(operation: Callable[[_Service], _Result], service_type: type[_Service] = ODApplicationService) -> _Result:
    try:
        return operation(service_type(get_session_factory(), storage_service))
    except ApplicationError as error:
        raise _error(error.status, str(error)) from None
    except (SQLAlchemyError, OSError, ValueError, RuntimeError):
        raise _error(503, "The OD service is temporarily unavailable.") from None


async def _bounded_body(request: Request, maximum: int) -> AsyncIterator[bytes]:
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum:
            raise _error(413, "The upload is too large.")
        yield chunk


async def _read_file(upload: UploadFile, *, image_only: bool = False) -> PrivateUpload:
    filename = upload.filename or ""
    suffix = PurePath(filename).suffix.lower()
    if len(filename) > 255 or not filename.isprintable() or any(char in filename for char in "/\\:"):
        raise _error(422, "Use a valid document filename.")
    if suffix not in _FILE_TYPES:
        raise _error(415, "Documents must be PDF, PNG or JPEG files.")
    if image_only and suffix == ".pdf":
        raise _error(415, "The venue photo must be a PNG or JPEG image.")
    media_type, signature, ending = _FILE_TYPES[suffix]
    maximum = settings.MAX_UPLOAD_SIZE_BYTES
    content = await upload.read(maximum + 1)
    if len(content) > maximum:
        raise _error(413, "A document exceeds the upload size limit.")
    trailer_valid = b"%%EOF" in content[-1024:] if suffix == ".pdf" else content.endswith(ending)
    if (
        upload.content_type not in (None, "application/octet-stream", media_type)
        or not content.startswith(signature)
        or not trailer_valid
    ):
        raise _error(415, "A document does not match its declared file type.")
    return PrivateUpload(filename, media_type, content)


_Submission = TypeVar("_Submission", bound=ApplicationSubmission)


@asynccontextmanager
async def _upload_form(request: Request, file_count: int):
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "multipart/form-data":
        raise _error(415, "Submit the OD details and documents as multipart form data.")
    parser = MultiPartParser(
        request.headers, _bounded_body(request, file_count * settings.MAX_UPLOAD_SIZE_BYTES + 65536),
        max_files=file_count, max_fields=1, max_part_size=32768,
    )
    try:
        form = await parser.parse()
    except (MultiPartException, MultipartParseError, ClientDisconnect):
        raise _error(400, "Invalid OD upload.") from None
    try:
        yield form
    finally:
        await form.close()


async def _read_submission(
    request: Request, schema: type[_Submission], *, require_original: bool,
) -> tuple[_Submission, list[ODFile]]:
    async with _upload_form(request, 3 if require_original else 2) as form:
        details = form.get("details")
        if not isinstance(details, str):
            raise _error(422, "Application details are required.")
        try:
            submission = schema.model_validate_json(details)
        except ValidationError:
            raise _error(422, "Check the event information and provide distinct event dates.") from None
        files = []
        seen = {"details"}
        for name, value in form.multi_items():
            if name == "details":
                continue
            if name in seen or name not in _FIELDS or not isinstance(value, UploadFile):
                raise _error(422, "Unexpected document field.")
            if name == "original_form" and not require_original:
                raise _error(422, "The original signed OD form cannot be replaced.")
            seen.add(name)
            files.append(ODFile(_FIELDS[name], await _read_file(value)))
        if require_original and "original_form" not in seen:
            raise _error(422, "The original signed OD form is required.")
        return submission, files


@od_router.post("/applications", status_code=201)
async def submit(request: Request, response: Response, user: Student) -> ApplicationDetail:
    submission, files = await _read_submission(request, ApplicationSubmission, require_original=True)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_perform, lambda service: service.submit(user, submission, files))


@od_router.get("/applications")
def student_applications(response: Response, user: Student) -> list[ApplicationSummary]:
    response.headers.update(_NO_STORE)
    return _perform(lambda service: service.list_applications(user))


@od_router.get("/tutor/applications")
def tutor_applications(response: Response, user: Tutor) -> list[ApplicationSummary]:
    response.headers.update(_NO_STORE)
    return _perform(lambda service: service.list_applications(user))


@od_router.get("/applications/{application_id}")
def detail(application_id: UUID, response: Response, user: Participant) -> ApplicationDetail:
    response.headers.update(_NO_STORE)
    return _perform(lambda service: service.detail(user, application_id))


@od_router.post("/applications/{application_id}/resubmit")
async def resubmit(application_id: UUID, request: Request, response: Response, user: Student) -> ApplicationDetail:
    correction, files = await _read_submission(request, ApplicationCorrection, require_original=False)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_perform, lambda service: service.resubmit(user, application_id, correction, files))


@od_router.post("/tutor/applications/{application_id}/decision")
async def decide(application_id: UUID, request: Request, response: Response, user: Tutor) -> ApplicationDetail:
    decision = await read_auth_json(request, TutorDecision)
    if decision is None:
        raise _error(422, "Select a decision and enter remarks.")
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(_perform, lambda service: service.decide(user, application_id, decision))


@od_router.get("/applications/{application_id}/documents/{document_id}")
def download(application_id: UUID, document_id: UUID, user: Participant) -> Response:
    file = _perform(lambda service: service.download(user, application_id, document_id))
    return _attachment(file)


def _attachment(file: PrivateUpload) -> Response:
    return Response(file.content, media_type=file.media_type, headers={
        **_NO_STORE,
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.filename, safe='')}",
        "X-Content-Type-Options": "nosniff",
    })


@od_router.get("/applications/{application_id}/evidence")
def evidence(application_id: UUID, response: Response, user: Participant) -> ApplicationEvidenceView:
    response.headers.update(_NO_STORE)
    return _perform(lambda service: service.detail(user, application_id), ODEvidenceService)


@od_router.post("/applications/{application_id}/days/{day_id}/evidence", status_code=201)
async def submit_evidence(
    application_id: UUID, day_id: UUID, request: Request, response: Response, user: Student,
) -> ApplicationEvidenceView:
    async with _upload_form(request, 2) as form:
        if sorted(name for name, _ in form.multi_items()) != ["details", "organizer_proof", "venue_photo"]:
            raise _error(422, "GPS details, a venue photo and organizer proof are required.")
        details, photo, proof = form["details"], form["venue_photo"], form["organizer_proof"]
        if not isinstance(details, str) or not isinstance(photo, UploadFile) or not isinstance(proof, UploadFile):
            raise _error(422, "GPS details, a venue photo and organizer proof are required.")
        try:
            data = EvidenceUploadRequest.model_validate_json(details)
        except ValidationError:
            raise _error(422, "Provide valid GPS coordinates, accuracy and timestamps.") from None
        venue_photo = await _read_file(photo, image_only=True)
        organizer_proof = await _read_file(proof)
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(
        _perform, lambda service: service.submit(user, application_id, day_id, data, venue_photo, organizer_proof),
        ODEvidenceService,
    )


@od_router.post("/tutor/applications/{application_id}/days/{day_id}/evidence/{submission_id}/review")
async def review_evidence(
    application_id: UUID, day_id: UUID, submission_id: UUID, request: Request, response: Response, user: Tutor,
) -> ApplicationEvidenceView:
    decision = await read_auth_json(request, DayEvidenceDecision)
    if decision is None:
        raise _error(422, "Select a decision and enter remarks.")
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(
        _perform, lambda service: service.review(user, application_id, day_id, submission_id, decision),
        ODEvidenceService,
    )


@od_router.get("/applications/{application_id}/evidence/{submission_id}/files/{kind}")
def download_evidence(
    application_id: UUID, submission_id: UUID, kind: Literal["venue-photo", "organizer-proof"], user: Participant,
) -> Response:
    file = _perform(lambda service: service.download(user, application_id, submission_id, kind), ODEvidenceService)
    return _attachment(file)
