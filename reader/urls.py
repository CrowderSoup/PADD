from django.urls import include, path

urlpatterns = [
    path("", include("microsub_client.urls")),
]
