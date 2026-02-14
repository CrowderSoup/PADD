import secrets

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static

from pathlib import Path

from django.conf import settings

from . import api, micropub
from .auth import (
    build_authorization_url,
    discover_endpoints,
    exchange_code_for_token,
    fetch_hcard,
    generate_pkce_pair,
)
from .models import Broadcast, CachedEntry, Interaction
from .utils import get_entry_type, sanitize_content, format_datetime


# --- PWA Views ---


def offline_view(request):
    return render(request, "offline.html")


def service_worker_view(request):
    sw_path = Path(__file__).resolve().parent / "static" / "sw.js"
    return HttpResponse(sw_path.read_text(), content_type="application/javascript")


# --- Auth Views ---


def _client_id(request):
    return request.build_absolute_uri("/id")


def client_id_metadata_view(request):
    client_uri = request.build_absolute_uri("/")
    return JsonResponse(
        {
            "client_id": _client_id(request),
            "client_name": "PADD",
            "client_uri": client_uri,
            "logo_uri": request.build_absolute_uri(static("logo.svg")),
            "redirect_uris": [request.build_absolute_uri("/login/callback/")],
            "scope": "read follow channels create",
        }
    )


def login_view(request):
    if request.session.get("access_token"):
        return redirect("index")

    error = None
    if request.method == "POST":
        url = request.POST.get("url", "").strip()
        if not url:
            error = "Please enter your domain."
        else:
            try:
                endpoints = discover_endpoints(url)
                if not endpoints["authorization_endpoint"]:
                    error = "Could not find an authorization endpoint for that URL."
                elif not endpoints["token_endpoint"]:
                    error = "Could not find a token endpoint for that URL."
                elif not endpoints["microsub"]:
                    error = "Could not find a Microsub endpoint for that URL."
                else:
                    state = secrets.token_urlsafe(32)
                    code_verifier, code_challenge = generate_pkce_pair()
                    request.session["auth_state"] = state
                    request.session["code_verifier"] = code_verifier
                    request.session["token_endpoint"] = endpoints["token_endpoint"]
                    request.session["microsub_endpoint"] = endpoints["microsub"]
                    if endpoints.get("micropub"):
                        request.session["micropub_endpoint"] = endpoints["micropub"]
                    request.session["user_url"] = url

                    client_id = _client_id(request)
                    redirect_uri = request.build_absolute_uri("/login/callback/")

                    auth_url = build_authorization_url(
                        endpoints["authorization_endpoint"],
                        me=url,
                        redirect_uri=redirect_uri,
                        state=state,
                        client_id=client_id,
                        code_challenge=code_challenge,
                    )
                    return redirect(auth_url)
            except ValueError as exc:
                error = str(exc)

    return render(request, "login.html", {"error": error})


def callback_view(request):
    code = request.GET.get("code")
    state = request.GET.get("state")

    if not code or not state:
        return redirect("login")

    expected_state = request.session.get("auth_state")
    if state != expected_state:
        return redirect("login")

    token_endpoint = request.session.get("token_endpoint")
    code_verifier = request.session.get("code_verifier")
    if not token_endpoint or not code_verifier:
        return redirect("login")

    client_id = _client_id(request)
    redirect_uri = request.build_absolute_uri("/login/callback/")

    try:
        result = exchange_code_for_token(
            token_endpoint, code, redirect_uri, client_id, code_verifier
        )
    except ValueError:
        return redirect("login")

    request.session["access_token"] = result["access_token"]
    # Clean up temporary auth state
    request.session.pop("auth_state", None)
    request.session.pop("token_endpoint", None)
    request.session.pop("code_verifier", None)

    # Fetch h-card for user display name and photo
    user_url = request.session.get("user_url", "")
    if user_url:
        hcard = fetch_hcard(user_url)
        if hcard.get("name"):
            request.session["user_name"] = hcard["name"]
        if hcard.get("photo"):
            request.session["user_photo"] = hcard["photo"]

    return redirect("index")


def logout_view(request):
    request.session.flush()
    return redirect("login")


def settings_view(request):
    if not request.session.get("access_token"):
        return redirect("login")

    if request.method == "POST":
        default_filter = request.POST.get("default_filter", "all")
        request.session["default_filter"] = default_filter
        return redirect("settings")

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    return render(request, "settings.html", {
        "default_filter": request.session.get("default_filter", "all"),
        "channels": channels,
    })


# --- Main Views ---


def index_view(request):
    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]

    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        request.session.flush()
        return redirect("login")

    if not channels:
        return render(request, "timeline.html", {"channels": [], "entries": []})

    first = channels[0]
    return redirect("timeline", channel_uid=first.get("uid", "default"))


def _enrich_entries(entries, request):
    """Add template-friendly fields to entry dicts."""
    has_micropub = bool(request.session.get("micropub_endpoint"))
    user_url = request.session.get("user_url", "")

    for entry in entries:
        entry["display_type"] = get_entry_type(entry)
        for key in ("like-of", "repost-of", "in-reply-to", "bookmark-of"):
            if key in entry:
                entry[key.replace("-", "_")] = entry[key]
        if "_id" in entry:
            entry["entry_id"] = entry["_id"]
        if "_is_read" in entry:
            entry["is_read"] = entry["_is_read"]
        if "content" in entry:
            content = entry["content"]
            if isinstance(content, dict):
                html = content.get("html", content.get("text", ""))
            else:
                html = content
            entry["safe_content"] = sanitize_content(html)
        if "published" in entry:
            entry["formatted_date"] = format_datetime(entry["published"])

    # Look up existing interactions for displayed entries
    if has_micropub and user_url:
        entry_urls = [e.get("url") for e in entries if e.get("url")]
        interaction_set = set()
        interaction_data = {}
        if entry_urls:
            existing = Interaction.objects.filter(
                user_url=user_url,
                entry__url__in=entry_urls,
            ).values_list("entry__url", "kind", "content", "result_url")
            for url, kind, content, result_url in existing:
                interaction_set.add(f"{url}:{kind}")
                interaction_data[f"{url}:{kind}"] = {
                    "content": content,
                    "result_url": result_url,
                }

        for entry in entries:
            entry_url = entry.get("url", "")
            entry["user_liked"] = f"{entry_url}:like" in interaction_set
            entry["user_reposted"] = f"{entry_url}:repost" in interaction_set
            entry["user_replied"] = f"{entry_url}:reply" in interaction_set
            like_data = interaction_data.get(f"{entry_url}:like", {})
            repost_data = interaction_data.get(f"{entry_url}:repost", {})
            reply_data = interaction_data.get(f"{entry_url}:reply", {})
            entry["like_result_url"] = like_data.get("result_url", "")
            entry["repost_result_url"] = repost_data.get("result_url", "")
            entry["reply_url"] = reply_data.get("result_url", "")
            entry["reply_content"] = reply_data.get("content", "")

    return has_micropub


def timeline_view(request, channel_uid):
    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]

    after = request.GET.get("after")
    if "unread" in request.GET:
        unread_only = request.GET["unread"] == "1"
    else:
        unread_only = request.session.get("default_filter") == "unread"

    try:
        channels = api.get_channels(endpoint, token)
        timeline_data = api.get_timeline(
            endpoint, token, channel_uid, after=after,
            is_read=False if unread_only else None,
        )
    except api.MicrosubError:
        request.session.flush()
        return redirect("login")

    entries = timeline_data.get("items", [])
    paging = timeline_data.get("paging", {})
    after_cursor = paging.get("after")

    current_channel = None
    for ch in channels:
        if ch.get("uid") == channel_uid:
            current_channel = ch
            break

    has_micropub = _enrich_entries(entries, request)

    base_ctx = {
        "entries": entries,
        "channel_uid": channel_uid,
        "after_cursor": after_cursor,
        "unread_only": unread_only,
        "has_micropub": has_micropub,
    }

    # HTMX partial for "load more"
    if request.htmx and after:
        return render(request, "partials/timeline_entries.html", base_ctx)

    # HTMX partial for channel switching (includes OOB sidebar update)
    if request.htmx:
        base_ctx.update({
            "channels": channels,
            "channel_name": current_channel.get("name", "") if current_channel else "",
            "wrap_full": True,
        })
        return render(request, "partials/channel_switch.html", base_ctx)

    base_ctx.update({
        "channels": channels,
        "current_channel": current_channel,
    })
    return render(request, "timeline.html", base_ctx)


def mark_read_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel = request.POST.get("channel")
    entry = request.POST.get("entry")

    if not channel or not entry:
        return HttpResponse(status=400)

    try:
        api.mark_read(endpoint, token, channel, entry)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return HttpResponse(
        '<span class="lcars-read-status lcars-read">Read</span>',
        status=200,
    )


# --- Micropub Views ---


def _get_or_create_cached_entry(url):
    entry, _ = CachedEntry.objects.get_or_create(url=url)
    return entry


def micropub_like_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    mp_endpoint = request.session.get("micropub_endpoint")
    if not mp_endpoint:
        return HttpResponse("Micropub not available", status=400)

    token = request.session["access_token"]
    user_url = request.session["user_url"]
    entry_url = request.POST.get("entry_url")
    if not entry_url:
        return HttpResponse(status=400)

    cached = _get_or_create_cached_entry(entry_url)
    existing = Interaction.objects.filter(
        user_url=user_url, entry=cached, kind="like"
    ).first()
    if existing:
        return render(request, "partials/interaction_buttons.html", {
            "kind": "like", "active": True, "entry_url": entry_url,
            "result_url": existing.result_url,
        })

    try:
        result_url = micropub.like(mp_endpoint, token, entry_url)
    except micropub.MicropubError as exc:
        return HttpResponse(f"Error: {exc}", status=502)

    Interaction.objects.create(
        user_url=user_url, entry=cached, kind="like", result_url=result_url,
    )

    return render(request, "partials/interaction_buttons.html", {
        "kind": "like", "active": True, "entry_url": entry_url,
        "result_url": result_url,
    })


def micropub_repost_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    mp_endpoint = request.session.get("micropub_endpoint")
    if not mp_endpoint:
        return HttpResponse("Micropub not available", status=400)

    token = request.session["access_token"]
    user_url = request.session["user_url"]
    entry_url = request.POST.get("entry_url")
    if not entry_url:
        return HttpResponse(status=400)

    cached = _get_or_create_cached_entry(entry_url)
    existing = Interaction.objects.filter(
        user_url=user_url, entry=cached, kind="repost"
    ).first()
    if existing:
        return render(request, "partials/interaction_buttons.html", {
            "kind": "repost", "active": True, "entry_url": entry_url,
            "result_url": existing.result_url,
        })

    try:
        result_url = micropub.repost(mp_endpoint, token, entry_url)
    except micropub.MicropubError as exc:
        return HttpResponse(f"Error: {exc}", status=502)

    Interaction.objects.create(
        user_url=user_url, entry=cached, kind="repost", result_url=result_url,
    )

    return render(request, "partials/interaction_buttons.html", {
        "kind": "repost", "active": True, "entry_url": entry_url,
        "result_url": result_url,
    })


def micropub_reply_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    mp_endpoint = request.session.get("micropub_endpoint")
    if not mp_endpoint:
        return HttpResponse("Micropub not available", status=400)

    token = request.session["access_token"]
    user_url = request.session["user_url"]
    entry_url = request.POST.get("entry_url")
    content = request.POST.get("content", "").strip()
    if not entry_url or not content:
        return HttpResponse(status=400)

    cached = _get_or_create_cached_entry(entry_url)

    try:
        result_url = micropub.reply(mp_endpoint, token, entry_url, content)
    except micropub.MicropubError as exc:
        return HttpResponse(f"Error: {exc}", status=502)

    Interaction.objects.update_or_create(
        user_url=user_url, entry=cached, kind="reply",
        defaults={"content": content, "result_url": result_url},
    )

    return render(request, "partials/reply_response.html", {
        "entry_url": entry_url,
        "reply_content": content, "reply_url": result_url,
    })


# --- Broadcast Views ---


def _is_admin(request):
    return request.session.get("user_url", "") in settings.PADD_ADMIN_URLS


def broadcast_admin_view(request):
    if not _is_admin(request):
        return HttpResponse(status=403)

    broadcasts = Broadcast.objects.all()
    return render(request, "broadcast_admin.html", {"broadcasts": broadcasts})


def broadcast_create_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    if not _is_admin(request):
        return HttpResponse(status=403)

    message = request.POST.get("message", "").strip()
    if message:
        Broadcast.objects.create(message=message)

    return redirect("broadcast-admin")


def broadcast_toggle_view(request, broadcast_id):
    if request.method != "POST":
        return HttpResponse(status=405)
    if not _is_admin(request):
        return HttpResponse(status=403)

    try:
        broadcast = Broadcast.objects.get(id=broadcast_id)
    except Broadcast.DoesNotExist:
        return HttpResponse(status=404)

    broadcast.is_active = not broadcast.is_active
    broadcast.save()
    return redirect("broadcast-admin")


def broadcast_dismiss_view(request, broadcast_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    dismissed = request.session.get("dismissed_broadcasts", [])
    if broadcast_id not in dismissed:
        dismissed.append(broadcast_id)
        request.session["dismissed_broadcasts"] = dismissed

    return HttpResponse("")


def broadcast_banner_view(request):
    """Returns the broadcast banner partial for HTMX polling."""
    return render(request, "partials/broadcast_banner.html")
