from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.utils.security import create_access_token
from tests.factories import DeveloperFactory


@pytest.mark.parametrize("user_id", [None, str(uuid4())])
def test_delivery_user_filter_uses_svix_channel(client: TestClient, user_id: str | None) -> None:
    developer = DeveloperFactory()
    with patch("app.api.routes.v1.outgoing_webhooks.svix_service") as service:
        service.is_enabled.return_value = True
        service.ensure_application.return_value = "app_test"
        service.list_message_attempts.return_value = MagicMock(data=[], done=True, iterator=None, prev_iterator=None)
        params = {"user_id": user_id} if user_id else {}
        response = client.get(
            "/api/v1/webhooks/endpoints/ep_test/attempts",
            params=params,
            headers={"Authorization": f"Bearer {create_access_token(developer.id)}"},
        )
        assert response.status_code == 200
        options = service.list_message_attempts.call_args.args[2]
        assert options.channel == (f"user.{user_id}" if user_id else None)


def test_delivery_user_filter_rejects_invalid_uuid(client: TestClient) -> None:
    developer = DeveloperFactory()
    with patch("app.api.routes.v1.outgoing_webhooks.svix_service") as service:
        service.is_enabled.return_value = True
        service.ensure_application.return_value = "app_test"
        response = client.get(
            "/api/v1/webhooks/endpoints/ep_test/attempts",
            params={"user_id": "invalid"},
            headers={"Authorization": f"Bearer {create_access_token(developer.id)}"},
        )
        assert response.status_code == 400
        service.list_message_attempts.assert_not_called()
