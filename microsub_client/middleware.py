from django.shortcuts import redirect


class MicrosubAuthMiddleware:
    PUBLIC_EXACT_PATHS = {"/", "/id", "/sw.js"}
    PUBLIC_PATH_PREFIXES = ("/login/", "/static/", "/offline/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_public = request.path in self.PUBLIC_EXACT_PATHS or any(
            request.path.startswith(prefix) for prefix in self.PUBLIC_PATH_PREFIXES
        )
        if not is_public:
            if not request.session.get("access_token"):
                return redirect("login")
        return self.get_response(request)
