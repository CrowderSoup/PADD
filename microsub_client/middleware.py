from django.shortcuts import redirect


class MicrosubAuthMiddleware:
    PUBLIC_PATHS = ("/login/", "/login/callback/", "/id", "/static/", "/offline/", "/sw.js")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not any(request.path.startswith(p) for p in self.PUBLIC_PATHS):
            if not request.session.get("access_token"):
                return redirect("login")
        return self.get_response(request)
