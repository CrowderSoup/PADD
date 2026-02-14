from django.urls import path

from . import views

urlpatterns = [
    path("", views.index_view, name="index"),
    path("offline/", views.offline_view, name="offline"),
    path("sw.js", views.service_worker_view, name="service-worker"),
    path("id", views.client_id_metadata_view, name="client-id-metadata"),
    path("login/", views.login_view, name="login"),
    path("login/callback/", views.callback_view, name="callback"),
    path("logout/", views.logout_view, name="logout"),
    path("settings/", views.settings_view, name="settings"),
    path("channel/<path:channel_uid>/", views.timeline_view, name="timeline"),
    path("api/mark-read/", views.mark_read_view, name="mark-read"),
    path("api/micropub/like/", views.micropub_like_view, name="micropub-like"),
    path("api/micropub/repost/", views.micropub_repost_view, name="micropub-repost"),
    path("api/micropub/reply/", views.micropub_reply_view, name="micropub-reply"),
    path("admin/broadcasts/", views.broadcast_admin_view, name="broadcast-admin"),
    path("admin/broadcasts/create/", views.broadcast_create_view, name="broadcast-create"),
    path("admin/broadcasts/<int:broadcast_id>/toggle/", views.broadcast_toggle_view, name="broadcast-toggle"),
    path("api/broadcast/<int:broadcast_id>/dismiss/", views.broadcast_dismiss_view, name="broadcast-dismiss"),
    path("api/broadcasts/", views.broadcast_banner_view, name="broadcast-banner"),
]
