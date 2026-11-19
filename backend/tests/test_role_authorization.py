import secrets
from typing import Annotated
from unittest.mock import patch

import jwt
from fastapi import APIRouter, Depends, FastAPI, Response
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import update

from app.core.access_tokens import create_access_token, verify_access_token
from app.dependencies.auth import AuthenticatedUser, require_roles
from app.models.enums import AccountStatus, UserRole
from app.models.user import User
from tests.auth_api_fixture import AuthSessionAPITestCase


router = APIRouter()


@router.get("/student")
def student_route(user: Annotated[AuthenticatedUser, Depends(require_roles(UserRole.STUDENT))]):
    return {"id": str(user.user_id)}


@router.get("/tutor", dependencies=[Depends(require_roles(UserRole.TUTOR))])
@router.get("/admin", dependencies=[Depends(require_roles(UserRole.ADMIN))])
@router.get("/staff", dependencies=[Depends(require_roles(UserRole.TUTOR, UserRole.ADMIN))])
def allowed_route():
    return Response(status_code=204)


class RoleAuthorizationTests(AuthSessionAPITestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = await self.enterAsyncContext(
            AsyncClient(transport=ASGITransport(app=app), base_url="https://api.example.com"),
        )

    def token(self):
        return create_access_token(self.user_id, self.initial.session_id)

    def set_user(self, **changes):
        with self.factory.begin() as db:
            db.execute(update(User).where(User.id == self.user_id).values(**changes))

    async def get(self, path, token=None, *, params=None, headers=None):
        headers = dict(headers or {})
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return await self.client.get(path, headers=headers, params=params)

    def assert_unauthorized(self, response):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid authentication credentials."})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def assert_forbidden(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Insufficient permissions."})
        self.assertNotIn("www-authenticate", response.headers)
        self.assertEqual(response.headers["cache-control"], "no-store")

    async def test_student_can_access_student_route_and_receives_authenticated_identity(self):
        response = await self.get("/student", self.token())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": str(self.user_id)})

    async def test_tutor_can_access_tutor_route(self):
        self.set_user(role=UserRole.TUTOR)
        self.assertEqual((await self.get("/tutor", self.token())).status_code, 204)

    async def test_admin_can_access_admin_route(self):
        self.set_user(role=UserRole.ADMIN)
        self.assertEqual((await self.get("/admin", self.token())).status_code, 204)

    async def test_multi_role_route_allows_each_listed_role(self):
        token = self.token()
        self.assert_forbidden(await self.get("/staff", token))
        for role in (UserRole.TUTOR, UserRole.ADMIN):
            with self.subTest(role=role):
                self.set_user(role=role)
                self.assertEqual((await self.get("/staff", token)).status_code, 204)

    async def test_wrong_roles_receive_forbidden_without_implicit_admin_access(self):
        token = self.token()
        self.assert_forbidden(await self.get("/tutor", token))
        self.assert_forbidden(await self.get("/admin", token))
        self.set_user(role=UserRole.ADMIN)
        self.assert_forbidden(await self.get("/student", token))
        self.assert_forbidden(await self.get("/tutor", token))

    async def test_missing_or_invalid_authentication_returns_401_before_role_check(self):
        for token in (None, "malformed"):
            self.assert_unauthorized(await self.get("/admin", token))
        self.current_user_factory.assert_not_called()

    async def test_existing_token_uses_current_database_role(self):
        token = self.token()
        self.assertEqual((await self.get("/student", token)).status_code, 200)
        self.assert_forbidden(await self.get("/tutor", token))
        self.set_user(role=UserRole.TUTOR)
        self.assert_forbidden(await self.get("/student", token))
        self.assertEqual((await self.get("/tutor", token)).status_code, 204)

    async def test_disabled_account_is_unauthorized_even_with_allowed_role(self):
        self.set_user(role=UserRole.ADMIN)
        token = self.token()
        self.set_user(account_status=AccountStatus.DISABLED)
        self.assert_unauthorized(await self.get("/admin", token))

    async def test_revoked_session_is_unauthorized_even_with_allowed_role(self):
        self.set_user(role=UserRole.ADMIN)
        token = self.token()
        self.service.revoke_session(self.initial.session_id, user_id=self.user_id)
        self.assert_unauthorized(await self.get("/admin", token))

    async def test_client_role_parameters_and_headers_do_not_grant_access(self):
        self.assert_forbidden(await self.get(
            "/admin", self.token(), params={"role": "ADMIN"}, headers={"X-User-Role": "ADMIN"},
        ))

    async def test_jwt_role_claim_cannot_grant_access(self):
        signing_key = secrets.token_urlsafe(48)
        with patch("app.core.access_tokens.settings.JWT_SIGNING_SECRET", SecretStr(signing_key)):
            token = self.token()
            self.assert_forbidden(await self.get("/admin", token))
            claims = verify_access_token(token).model_dump(mode="json")
            claims["role"] = "ADMIN"
            for key in (secrets.token_urlsafe(48), signing_key):
                modified = jwt.encode(claims, key, algorithm="HS256", headers={"typ": "at+jwt"})
                self.assert_unauthorized(await self.get("/admin", modified))

    def test_role_configuration_requires_at_least_one_role(self):
        with self.assertRaises(TypeError):
            require_roles()
