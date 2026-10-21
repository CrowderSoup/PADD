from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answers kamal-proxy's /up/ health check before anything validates the
    Host header.

    kamal-proxy probes the container directly, so the request's Host is the
    container's own name (e.g. padd-web-<sha>:8000), which is never in
    ALLOWED_HOSTS. Short-circuiting here lets ALLOWED_HOSTS stay a strict
    list instead of needing "*" just for health checks. Must be first in
    MIDDLEWARE.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/up/":
            return HttpResponse("OK")
        return self.get_response(request)
