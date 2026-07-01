from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path("up/", lambda request: HttpResponse("OK")),
    path("", include("microsub_client.urls")),
]
