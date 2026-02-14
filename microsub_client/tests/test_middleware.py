from unittest.mock import Mock

from django.test import RequestFactory, TestCase

from microsub_client.middleware import MicrosubAuthMiddleware


class MicrosubAuthMiddlewareTests(TestCase):
    def setUp(self):
        self.get_response = Mock(return_value=Mock(status_code=200))
        self.middleware = MicrosubAuthMiddleware(self.get_response)
        self.factory = RequestFactory()

    def _make_request(self, path, session=None):
        request = self.factory.get(path)
        request.session = session or {}
        return request

    def test_public_path_login_allowed(self):
        request = self._make_request("/login/")
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_public_path_callback_allowed(self):
        request = self._make_request("/login/callback/")
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_public_path_id_allowed(self):
        request = self._make_request("/id")
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_public_path_static_allowed(self):
        request = self._make_request("/static/style.css")
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_public_path_offline_allowed(self):
        request = self._make_request("/offline/")
        self.middleware(request)
        self.get_response.assert_called_once_with(request)

    def test_private_path_without_token_redirects(self):
        request = self._make_request("/channel/default/")
        response = self.middleware(request)
        self.assertEqual(response.status_code, 302)
        self.get_response.assert_not_called()

    def test_private_path_with_token_passes(self):
        request = self._make_request("/channel/default/", session={"access_token": "tok"})
        self.middleware(request)
        self.get_response.assert_called_once_with(request)
