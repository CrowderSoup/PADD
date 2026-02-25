import datetime
import json
import secrets
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static

from pathlib import Path

from django.conf import settings

from . import api, image_utils, micropub
from .auth import (
    build_authorization_url,
    discover_endpoints,
    exchange_code_for_token,
    fetch_hcard,
    generate_pkce_pair,
)
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q

from .models import Broadcast, CachedEntry, DismissedBroadcast, Draft, Interaction, KnownUser, UserSettings
from .utils import get_entry_type, sanitize_content, format_datetime


# --- PWA Views ---


def offline_view(request):
    return render(request, "offline.html")


def service_worker_view(request):
    sw_path = Path(__file__).resolve().parent / "static" / "sw.js"
    try:
        return HttpResponse(sw_path.read_text(), content_type="application/javascript")
    except FileNotFoundError:
        return HttpResponse(status=404)


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


def landing_view(request):
    if request.session.get("access_token"):
        return redirect("index")
    return render(request, "landing.html")


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

        KnownUser.objects.update_or_create(
            url=user_url,
            defaults={
                "name": hcard.get("name") or "",
                "photo": hcard.get("photo") or "",
            },
        )

    return redirect("index")


def logout_view(request):
    request.session.flush()
    return redirect("login")


def settings_view(request):
    if not request.session.get("access_token"):
        return redirect("login")
    if not request.session.get("user_url"):
        return redirect("login")

    user_settings = _get_user_settings(request)

    if request.method == "POST":
        _valid_filters = {"all", "unread"}
        _valid_mrb = set(UserSettings.MarkReadBehavior.values)
        df = request.POST.get("default_filter", "all")
        user_settings.default_filter = df if df in _valid_filters else "all"
        mrb = request.POST.get("mark_read_behavior", UserSettings.MarkReadBehavior.EXPLICIT)
        user_settings.mark_read_behavior = mrb if mrb in _valid_mrb else UserSettings.MarkReadBehavior.EXPLICIT
        user_settings.expand_content = request.POST.get("expand_content") == "on"
        user_settings.infinite_scroll = request.POST.get("infinite_scroll") == "on"
        user_settings.show_gardn_harvest = request.POST.get("show_gardn_harvest") == "on"
        user_settings.save()
        if request.htmx:
            return render(request, "partials/settings_form.html", {
                "default_filter": user_settings.default_filter,
                "mark_read_behavior": user_settings.mark_read_behavior,
                "expand_content": user_settings.expand_content,
                "infinite_scroll": user_settings.infinite_scroll,
                "show_gardn_harvest": user_settings.show_gardn_harvest,
            })
        return redirect("settings")

    endpoint = request.session.get("microsub_endpoint")
    token = request.session.get("access_token")
    if not endpoint or not token:
        return redirect("login")
    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    return render(request, "settings.html", {
        "default_filter": user_settings.default_filter,
        "mark_read_behavior": user_settings.mark_read_behavior,
        "expand_content": user_settings.expand_content,
        "infinite_scroll": user_settings.infinite_scroll,
        "show_gardn_harvest": user_settings.show_gardn_harvest,
        "channels": channels,
    })


def _get_user_settings(request):
    user_url = request.session.get("user_url")
    if not user_url:
        raise ValueError("Missing user_url in session")

    settings_obj, _ = UserSettings.objects.get_or_create(
        user_url=user_url
    )
    return settings_obj


# --- Main Views ---


def index_view(request):
    endpoint = request.session.get("microsub_endpoint")
    token = request.session.get("access_token")
    if not endpoint or not token:
        return redirect("login")

    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        request.session.flush()
        return redirect("login")

    if not channels:
        return render(request, "timeline.html", {"channels": [], "entries": []})

    first = channels[0]
    return redirect("timeline", channel_uid=first.get("uid", "default"))


def _parse_location(entry):
    """Extract latitude and longitude from an entry's location or checkin data.

    Handles three formats:
    - geo: URI strings (e.g. "geo:37.786,-122.399")
    - dicts with latitude/lat and longitude/lng/long keys
    - checkin h-card dicts (u-checkin with p-latitude/p-longitude)

    Returns:
        tuple: (lat, lng) as floats, or (None, None) if no valid location found.
    """
    loc = entry.get("location")
    if isinstance(loc, list):
        loc = loc[0] if loc else None

    if isinstance(loc, str) and loc.startswith("geo:"):
        parts = loc[4:].split(",")
        if len(parts) >= 2:
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                pass
    elif isinstance(loc, dict):
        try:
            lat = float(loc.get("latitude") or loc.get("lat") or "")
            lng = float(loc.get("longitude") or loc.get("lng") or loc.get("long") or "")
            return lat, lng
        except (ValueError, TypeError):
            pass

    # Fall back to checkin h-card (u-checkin with p-latitude/p-longitude)
    checkin = entry.get("checkin")
    if isinstance(checkin, list):
        checkin = checkin[0] if checkin else None
    if isinstance(checkin, dict):
        try:
            lat = float(checkin.get("latitude") or checkin.get("lat") or "")
            lng = float(checkin.get("longitude") or checkin.get("lng") or checkin.get("long") or "")
            return lat, lng
        except (ValueError, TypeError):
            pass

    return None, None


def _lookup_interactions(entries, user_url):
    """Query the database for existing interactions on the given entries.

    Args:
        entries: List of entry dicts, each expected to have a "url" key.
        user_url: The authenticated user's profile URL.

    Returns:
        tuple: (interaction_set, interaction_data) where
            - interaction_set is a set of "url:kind" strings for fast membership testing
            - interaction_data is a dict of "url:kind" -> {"content": ..., "result_url": ...}
    """
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
    return interaction_set, interaction_data


def _enrich_entries(entries, request):
    """Add template-friendly fields to entry dicts, mutating each entry in place.

    Normalizes field names, sanitizes HTML content, formats dates, extracts
    location coordinates, and annotates each entry with the user's interaction
    state (liked, reposted, replied).

    Args:
        entries: List of entry dicts from the Microsub API.
        request: The current Django request (reads session for endpoint/user info).

    Returns:
        bool: True if the user has a Micropub endpoint configured.
    """
    has_micropub = bool(request.session.get("micropub_endpoint"))
    user_url = request.session.get("user_url", "")

    for entry in entries:
        # Templates may reference entry.url in filter arguments; ensure key exists.
        entry.setdefault("url", "")
        entry["display_type"] = get_entry_type(entry)
        for key in ("like-of", "repost-of", "in-reply-to", "bookmark-of"):
            if key in entry:
                val = entry[key]
                if isinstance(val, list):
                    val = val[0] if val else ""
                underscore_key = key.replace("-", "_")
                entry[underscore_key] = val
                if isinstance(val, dict):
                    entry[underscore_key + "_context"] = val
        if "_id" in entry:
            entry["entry_id"] = entry["_id"]
        if "_is_read" in entry:
            entry["is_read"] = entry["_is_read"]
        if "content" in entry:
            content = entry["content"]
            html = content.get("html", content.get("text", "")) if isinstance(content, dict) else content
            entry["safe_content"] = sanitize_content(html)
        if "published" in entry:
            entry["formatted_date"] = format_datetime(entry["published"])
        lat, lng = _parse_location(entry)
        if lat is not None and lng is not None:
            entry["has_location"] = True
            entry["location_lat"] = round(lat, 6)
            entry["location_lng"] = round(lng, 6)

    if has_micropub and user_url:
        interaction_set, interaction_data = _lookup_interactions(entries, user_url)
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
    endpoint = request.session.get("microsub_endpoint")
    token = request.session.get("access_token")
    if not endpoint or not token or not request.session.get("user_url"):
        return redirect("login")

    user_settings = _get_user_settings(request)

    after = request.GET.get("after")
    if "unread" in request.GET:
        unread_only = request.GET["unread"] == "1"
    else:
        unread_only = user_settings.default_filter == "unread"

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
        "expand_content": user_settings.expand_content,
        "mark_read_behavior": user_settings.mark_read_behavior,
        "infinite_scroll": user_settings.infinite_scroll,
        "show_gardn_harvest": user_settings.show_gardn_harvest,
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
    entries = request.POST.getlist("entry")
    # Also accept entry[] for batch calls
    entries += request.POST.getlist("entry[]")

    if not channel or not entries:
        return HttpResponse(status=400)

    try:
        api.mark_read(endpoint, token, channel, entries)
    except api.MicrosubError:
        return HttpResponse(status=502)

    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    return render(request, "partials/mark_read_response.html", {
        "channels": channels,
        "channel_uid": channel,
        "entries": entries,
    })


def mark_unread_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel = request.POST.get("channel")
    entry = request.POST.get("entry")

    if not channel or not entry:
        return HttpResponse(status=400)

    try:
        api.mark_unread(endpoint, token, channel, entry)
    except api.MicrosubError:
        return HttpResponse(status=502)

    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    return render(request, "partials/mark_unread_response.html", {
        "channels": channels,
        "channel_uid": channel,
        "entry_id": entry,
    })


def remove_entry_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel = request.POST.get("channel")
    entry = request.POST.get("entry")

    if not channel or not entry:
        return HttpResponse(status=400)

    try:
        api.remove_entry(endpoint, token, channel, entry)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return HttpResponse("")


def mute_user_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    author_url = request.POST.get("author_url")
    channel = request.POST.get("channel") or None

    if not author_url:
        return HttpResponse(status=400)

    try:
        api.mute_user(endpoint, token, author_url, channel=channel)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return HttpResponse(status=204)


def unmute_user_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    author_url = request.POST.get("author_url")
    channel = request.POST.get("channel") or None

    if not author_url:
        return HttpResponse(status=400)

    try:
        api.unmute_user(endpoint, token, author_url, channel=channel)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return HttpResponse(status=204)


def block_user_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    author_url = request.POST.get("author_url")

    if not author_url:
        return HttpResponse(status=400)

    try:
        api.block_user(endpoint, token, author_url)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return HttpResponse(status=204)


# --- Channel Management Views ---


def channel_create_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    name = request.POST.get("name", "").strip()

    if not name:
        return HttpResponse(status=400)

    try:
        api.create_channel(endpoint, token, name)
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/channel_list.html", {
        "channels": channels,
    })


def channel_mark_read_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel_uid = request.POST.get("channel")

    if not channel_uid:
        return HttpResponse(status=400)

    try:
        api.mark_channel_read(endpoint, token, channel_uid)
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/channel_list.html", {
        "channels": channels,
    })


def channel_rename_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel_uid = request.POST.get("channel")
    name = request.POST.get("name", "").strip()

    if not channel_uid or not name:
        return HttpResponse(status=400)

    try:
        api.update_channel(endpoint, token, channel_uid, name)
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/channel_list.html", {
        "channels": channels,
    })


def channel_delete_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel_uid = request.POST.get("channel")

    if not channel_uid:
        return HttpResponse(status=400)

    try:
        api.delete_channel(endpoint, token, channel_uid)
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError as exc:
        return HttpResponse(str(exc), status=502)

    return render(request, "partials/channel_list.html", {
        "channels": channels,
    })


def channel_order_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel_uids = request.POST.getlist("channels[]")

    if not channel_uids:
        return HttpResponse(status=400)

    try:
        api.order_channels(endpoint, token, channel_uids)
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/channel_list.html", {
        "channels": channels,
    })


# --- Feed Management Views ---


def feed_search_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    query = request.POST.get("query", "").strip()
    channel_uid = request.POST.get("channel", "")

    if not query:
        return HttpResponse(status=400)

    try:
        result = api.search_feeds(endpoint, token, query)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/feed_search_results.html", {
        "results": result.get("results", []),
        "channel_uid": channel_uid,
    })


def feed_preview_view(request):
    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    url = request.GET.get("url", "").strip()

    if not url:
        return HttpResponse(status=400)

    try:
        result = api.preview_feed(endpoint, token, url)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/feed_preview.html", {
        "items": result.get("items", []),
        "url": url,
    })


def feed_list_view(request, channel_uid):
    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]

    try:
        result = api.get_follows(endpoint, token, channel_uid)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/feed_panel.html", {
        "feeds": result.get("items", []),
        "channel_uid": channel_uid,
    })


def feed_follow_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel_uid = request.POST.get("channel")
    url = request.POST.get("url", "").strip()

    if not channel_uid or not url:
        return HttpResponse(status=400)

    try:
        api.follow_feed(endpoint, token, channel_uid, url)
        result = api.get_follows(endpoint, token, channel_uid)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/feed_list.html", {
        "feeds": result.get("items", []),
        "channel_uid": channel_uid,
    })


def feed_unfollow_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    endpoint = request.session["microsub_endpoint"]
    token = request.session["access_token"]
    channel_uid = request.POST.get("channel")
    url = request.POST.get("url", "").strip()

    if not channel_uid or not url:
        return HttpResponse(status=400)

    try:
        api.unfollow_feed(endpoint, token, channel_uid, url)
        result = api.get_follows(endpoint, token, channel_uid)
    except api.MicrosubError:
        return HttpResponse(status=502)

    return render(request, "partials/feed_list.html", {
        "feeds": result.get("items", []),
        "channel_uid": channel_uid,
    })


# --- Micropub Views ---


def _get_or_create_cached_entry(url):
    entry, _ = CachedEntry.objects.get_or_create(url=url)
    return entry


def new_post_view(request):
    mp_endpoint = request.session.get("micropub_endpoint")
    if not mp_endpoint:
        return HttpResponse("Micropub not available", status=400)

    token = request.session.get("access_token")
    if not token:
        return HttpResponse("Not authenticated", status=400)

    user_url = request.session.get("user_url", "")

    has_media_endpoint = False
    syndicate_to = []
    try:
        config = micropub.query_config(mp_endpoint, token)
        media_endpoint_url = config.get("media-endpoint", "")
        has_media_endpoint = bool(media_endpoint_url)
        syndicate_to = config.get("syndicate-to", [])
        # Cache the endpoint URL so upload_media_view can skip this query.
        if media_endpoint_url:
            request.session["media_endpoint_url"] = media_endpoint_url
    except micropub.MicropubError:
        pass

    drafts = Draft.objects.filter(user_url=user_url).order_by("-updated_at") if user_url else []

    if request.method == "POST":
        content = request.POST.get("content", "").strip()
        if not content:
            draft_id_str = request.POST.get("draft_id", "")
            draft = None
            if draft_id_str:
                try:
                    draft = Draft.objects.get(pk=int(draft_id_str), user_url=user_url)
                except (Draft.DoesNotExist, ValueError):
                    pass
            return render(request, "new_post.html", {
                "error": "Content is required.",
                "has_media_endpoint": has_media_endpoint,
                "syndicate_to": syndicate_to,
                "drafts": drafts,
                "draft": draft,
                "hide_fab": True,
            })

        name = request.POST.get("name", "").strip() or None
        tags = request.POST.get("tags", "").strip()
        category = [t.strip() for t in tags.split(",") if t.strip()] or None
        photos = request.POST.getlist("photo")
        photo = [p for p in photos if p] or None
        location = request.POST.get("location", "").strip() or None
        syndicate_targets = request.POST.getlist("syndicate_to") or None

        try:
            result_url = micropub.create_post(
                mp_endpoint, token, content,
                name=name, category=category, photo=photo, location=location,
                syndicate_to=syndicate_targets,
            )
        except micropub.MicropubError as exc:
            draft_id_str = request.POST.get("draft_id", "")
            draft = None
            if draft_id_str:
                try:
                    draft = Draft.objects.get(pk=int(draft_id_str), user_url=user_url)
                except (Draft.DoesNotExist, ValueError):
                    pass
            return render(request, "new_post.html", {
                "error": f"Failed to publish: {exc}",
                "has_media_endpoint": has_media_endpoint,
                "syndicate_to": syndicate_to,
                "drafts": drafts,
                "draft": draft,
                "hide_fab": True,
            })

        # Delete the draft that was published
        draft_id_str = request.POST.get("draft_id", "")
        if draft_id_str and user_url:
            try:
                Draft.objects.filter(pk=int(draft_id_str), user_url=user_url).delete()
            except ValueError:
                pass

        return render(request, "new_post.html", {
            "success": True,
            "result_url": result_url,
            "has_media_endpoint": has_media_endpoint,
            "syndicate_to": syndicate_to,
            "drafts": Draft.objects.filter(user_url=user_url).order_by("-updated_at") if user_url else [],
            "hide_fab": True,
        })

    # Load a specific draft if ?draft=<id> is provided
    draft = None
    draft_id_str = request.GET.get("draft", "")
    if draft_id_str and user_url:
        try:
            draft = Draft.objects.get(pk=int(draft_id_str), user_url=user_url)
        except (Draft.DoesNotExist, ValueError):
            pass

    return render(request, "new_post.html", {
        "has_media_endpoint": has_media_endpoint,
        "syndicate_to": syndicate_to,
        "drafts": drafts,
        "draft": draft,
        "hide_fab": True,
    })


def draft_save_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    user_url = request.session.get("user_url", "")
    if not user_url:
        return HttpResponse(status=403)

    draft_id_str = request.POST.get("draft_id", "")
    title = request.POST.get("name", "").strip()
    content = request.POST.get("content", "").strip()
    tags = request.POST.get("tags", "").strip()
    photos_raw = request.POST.get("photos_json", "")
    location = request.POST.get("location", "").strip()

    # Collect photos from photo[] form fields
    photos = request.POST.getlist("photo")
    photos = [p for p in photos if p]
    if not photos and photos_raw:
        import json as _json
        try:
            photos = _json.loads(photos_raw)
        except (ValueError, TypeError):
            photos = []

    draft = None
    if draft_id_str:
        try:
            draft = Draft.objects.get(pk=int(draft_id_str), user_url=user_url)
        except (Draft.DoesNotExist, ValueError):
            draft = None

    if draft:
        draft.title = title
        draft.content = content
        draft.tags = tags
        draft.photos = photos
        draft.location = location
        draft.save()
    else:
        draft = Draft.objects.create(
            user_url=user_url,
            title=title,
            content=content,
            tags=tags,
            photos=photos,
            location=location,
        )

    drafts = Draft.objects.filter(user_url=user_url).order_by("-updated_at")
    response = render(request, "partials/draft_sidebar.html", {
        "drafts": drafts,
        "current_draft_id": draft.pk,
    })
    # Append OOB swap to update the hidden draft_id input
    oob_html = f'<input type="hidden" name="draft_id" id="draft-id" value="{draft.pk}" hx-swap-oob="true">'
    response.content = response.content + oob_html.encode()
    return response


def draft_delete_view(request, draft_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    user_url = request.session.get("user_url", "")
    if not user_url:
        return HttpResponse(status=403)

    # Determine which draft is currently loaded in the form (if any)
    current_draft_id_str = request.POST.get("draft_id", "")
    try:
        current_draft_id = int(current_draft_id_str)
    except (ValueError, TypeError):
        current_draft_id = None

    Draft.objects.filter(pk=draft_id, user_url=user_url).delete()

    drafts = Draft.objects.filter(user_url=user_url).order_by("-updated_at")

    # Only clear the form's draft_id when the deleted draft was the active one.
    # If a different draft was deleted, preserve the current ID so subsequent
    # saves continue updating the right record.
    if current_draft_id == draft_id:
        sidebar_current_id = None
        oob_value = ""
    else:
        sidebar_current_id = current_draft_id
        oob_value = str(current_draft_id) if current_draft_id else ""

    response = render(request, "partials/draft_sidebar.html", {
        "drafts": drafts,
        "current_draft_id": sidebar_current_id,
    })
    oob_html = f'<input type="hidden" name="draft_id" id="draft-id" value="{oob_value}" hx-swap-oob="true">'
    response.content = response.content + oob_html.encode()
    return response


def convert_image_view(request):
    """Convert an image to a web-native JPEG and return the bytes directly.

    The client sends a non-web-native file (HEIC, TIFF, …), receives a JPEG,
    and can open the result in the browser-side photo editor without ever
    persisting anything.
    """
    if request.method != "POST":
        return HttpResponse(status=405)
    if not request.session.get("access_token"):
        return JsonResponse({"error": "Not authenticated"}, status=403)

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse({"error": "No file provided"}, status=400)

    try:
        converted = image_utils.maybe_convert(uploaded_file)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=422)

    return HttpResponse(converted.read(), content_type=getattr(converted, "content_type", "image/jpeg"))


def upload_media_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    mp_endpoint = request.session.get("micropub_endpoint")
    if not mp_endpoint:
        return JsonResponse({"error": "Micropub not available"}, status=400)

    token = request.session.get("access_token")
    if not token:
        return JsonResponse({"error": "Not authenticated"}, status=400)

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return JsonResponse({"error": "No file provided"}, status=400)

    try:
        uploaded_file = image_utils.maybe_convert(uploaded_file)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=422)

    # Use the endpoint URL cached by new_post_view; fall back to a live query
    # if the session doesn't have it (e.g. direct API call without page load).
    media_endpoint = request.session.get("media_endpoint_url")
    if not media_endpoint:
        try:
            config = micropub.query_config(mp_endpoint, token)
            media_endpoint = config.get("media-endpoint")
            if not media_endpoint:
                return JsonResponse({"error": "No media endpoint available"}, status=400)
            request.session["media_endpoint_url"] = media_endpoint
        except micropub.MicropubError as exc:
            return JsonResponse({"error": str(exc)}, status=502)

    try:
        url = micropub.upload_media(media_endpoint, token, uploaded_file)
    except micropub.MicropubError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    return JsonResponse({"url": url})


def _handle_simple_micropub_interaction(request, kind):
    """Shared handler for idempotent single-URL micropub interactions (like, repost).

    Checks for an existing interaction before posting to avoid duplicates.
    On success, creates an Interaction record and returns the interaction_buttons partial.

    Args:
        request: The current Django request.
        kind: "like" or "repost".

    Returns:
        HttpResponse
    """
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
    existing = Interaction.objects.filter(user_url=user_url, entry=cached, kind=kind).first()
    if existing:
        return render(request, "partials/interaction_buttons.html", {
            "kind": kind, "active": True, "entry_url": entry_url,
            "result_url": existing.result_url,
        })

    micropub_fn = micropub.like if kind == "like" else micropub.repost
    try:
        result_url = micropub_fn(mp_endpoint, token, entry_url)
    except micropub.MicropubError as exc:
        return HttpResponse(f"Error: {exc}", status=502)

    Interaction.objects.create(user_url=user_url, entry=cached, kind=kind, result_url=result_url)

    return render(request, "partials/interaction_buttons.html", {
        "kind": kind, "active": True, "entry_url": entry_url,
        "result_url": result_url,
    })


def micropub_like_view(request):
    return _handle_simple_micropub_interaction(request, "like")


def micropub_repost_view(request):
    return _handle_simple_micropub_interaction(request, "repost")


def micropub_reply_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    mp_endpoint = request.session.get("micropub_endpoint")
    if not mp_endpoint:
        return HttpResponse("Micropub not available", status=400)

    token = request.session["access_token"]
    user_url = request.session["user_url"]
    entry_url = request.POST.get("entry_url")
    if not entry_url:
        return HttpResponse("Entry URL is required", status=400)
    content = request.POST.get("content", "").strip()
    if not content:
        return HttpResponse("Content is required", status=400)
    if len(content) > 50_000:
        return HttpResponse("Content is too long", status=400)

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


# --- OPML Views ---


def opml_export_view(request):
    if not request.session.get("access_token"):
        return redirect("login")

    endpoint = request.session.get("microsub_endpoint")
    token = request.session.get("access_token")
    if not endpoint or not token:
        return redirect("login")

    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    root = ET.Element("opml", version="2.0")
    head = ET.SubElement(root, "head")
    ET.SubElement(head, "title").text = "PADD Subscriptions"
    body = ET.SubElement(root, "body")

    for channel in channels:
        channel_name = channel.get("name", channel.get("uid", ""))
        folder = ET.SubElement(body, "outline", text=channel_name, title=channel_name)
        try:
            result = api.get_follows(endpoint, token, channel.get("uid", ""))
            feeds = result.get("items", [])
        except api.MicrosubError:
            feeds = []
        for feed in feeds:
            feed_url = feed.get("url", "")
            feed_name = feed.get("name", feed_url)
            if feed_url:
                ET.SubElement(folder, "outline",
                               type="rss",
                               text=feed_name,
                               title=feed_name,
                               xmlUrl=feed_url)

    xml_bytes = ET.tostring(root, encoding="unicode", xml_declaration=False)
    xml_output = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes
    response = HttpResponse(xml_output, content_type="application/xml; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="padd-subscriptions.opml"'
    return response


def opml_import_view(request):
    if not request.session.get("access_token"):
        return redirect("login")

    endpoint = request.session.get("microsub_endpoint")
    token = request.session.get("access_token")
    if not endpoint or not token:
        return redirect("login")

    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    if request.method == "GET":
        return render(request, "opml_import.html", {"channels": channels})

    uploaded_file = request.FILES.get("opml_file")
    if not uploaded_file:
        return render(request, "opml_import.html", {
            "channels": channels,
            "error": "No file uploaded.",
        })

    fallback_channel = request.POST.get("fallback_channel", "")
    valid_channel_uids = {ch.get("uid", "") for ch in channels if ch.get("uid")}

    try:
        tree = SafeET.parse(uploaded_file)
    except (ET.ParseError, DefusedXmlException) as exc:
        return render(request, "opml_import.html", {
            "channels": channels,
            "error": f"Could not parse OPML file: {exc}",
        })

    existing_channel_names = {ch.get("name", "").lower(): ch.get("uid") for ch in channels}
    results = []

    body = tree.find("body")
    if body is None:
        return render(request, "opml_import.html", {
            "channels": channels,
            "error": "OPML file has no <body> element.",
        })

    for child in body:
        child_type = child.get("type", "")
        xml_url = child.get("xmlUrl", "")

        if child_type == "rss" or xml_url:
            # Flat feed — assign to fallback channel
            target_uid = fallback_channel
            feed_url = xml_url or child.get("url", "")
            if not feed_url or not target_uid:
                results.append({"channel": "(flat feed)", "url": feed_url, "status": "skipped — no fallback channel"})
                continue
            if target_uid not in valid_channel_uids:
                results.append({"channel": "(flat feed)", "url": feed_url, "status": "skipped — invalid fallback channel"})
                continue
            try:
                api.follow_feed(endpoint, token, target_uid, feed_url)
                results.append({"channel": fallback_channel, "url": feed_url, "status": "ok"})
            except api.MicrosubError as exc:
                results.append({"channel": fallback_channel, "url": feed_url, "status": f"error: {exc}"})
        else:
            # Folder — treat each top-level folder as one channel.
            # Nested folders are flattened into that top-level channel.
            folder_name = (child.get("title") or child.get("text") or "").strip()
            if not folder_name:
                folder_name = "Imported"
            folder_name_lower = folder_name.lower()
            if folder_name_lower in existing_channel_names:
                channel_uid = existing_channel_names[folder_name_lower]
            else:
                try:
                    new_ch = api.create_channel(endpoint, token, folder_name)
                    channel_uid = new_ch.get("uid", "")
                    existing_channel_names[folder_name_lower] = channel_uid
                except api.MicrosubError as exc:
                    for feed_outline in child.iter("outline"):
                        feed_url = feed_outline.get("xmlUrl", "") or feed_outline.get("url", "")
                        if feed_url:
                            results.append({"channel": folder_name, "url": feed_url, "status": f"error creating channel: {exc}"})
                    continue

            seen_feed_urls = set()
            for feed_outline in child.iter("outline"):
                feed_url = feed_outline.get("xmlUrl", "") or feed_outline.get("url", "")
                if not feed_url or feed_url in seen_feed_urls:
                    continue
                seen_feed_urls.add(feed_url)
                try:
                    api.follow_feed(endpoint, token, channel_uid, feed_url)
                    results.append({"channel": folder_name, "url": feed_url, "status": "ok"})
                except api.MicrosubError as exc:
                    results.append({"channel": folder_name, "url": feed_url, "status": f"error: {exc}"})

    return render(request, "opml_import.html", {
        "channels": channels,
        "results": results,
    })


# --- Account Views ---


def account_export_view(request):
    if not request.session.get("access_token"):
        return redirect("login")

    user_url = request.session.get("user_url")
    if not user_url:
        return redirect("login")

    user_settings = _get_user_settings(request)

    drafts = list(Draft.objects.filter(user_url=user_url).values(
        "title", "content", "tags", "photos", "location", "created_at", "updated_at"
    ))

    interactions = list(
        Interaction.objects.filter(user_url=user_url)
        .select_related("entry")
        .values("kind", "content", "result_url", "created_at", "entry__url", "entry__title")
    )

    payload = {
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
        "user_url": user_url,
        "settings": {
            "default_filter": user_settings.default_filter,
            "mark_read_behavior": user_settings.mark_read_behavior,
            "expand_content": user_settings.expand_content,
            "infinite_scroll": user_settings.infinite_scroll,
            "show_gardn_harvest": user_settings.show_gardn_harvest,
        },
        "drafts": drafts,
        "interactions": interactions,
    }

    slug = user_url.replace("https://", "").replace("http://", "").strip("/").replace("/", "-")
    date_str = datetime.date.today().isoformat()
    filename = f"padd-export-{slug}-{date_str}.json"

    response = HttpResponse(
        json.dumps(payload, default=str, indent=2),
        content_type="application/json; charset=utf-8",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def account_delete_view(request):
    if not request.session.get("access_token"):
        return redirect("login")

    user_url = request.session.get("user_url")
    if not user_url:
        return redirect("login")

    error = None

    if request.method == "POST":
        confirm_url = request.POST.get("confirm_url", "").strip().rstrip("/")
        normalized = user_url.strip().rstrip("/")
        if confirm_url == normalized:
            UserSettings.objects.filter(user_url=user_url).delete()
            Draft.objects.filter(user_url=user_url).delete()
            Interaction.objects.filter(user_url=user_url).delete()
            DismissedBroadcast.objects.filter(user_url=user_url).delete()
            KnownUser.objects.filter(url=user_url).delete()
            request.session.flush()
            return redirect("landing")
        else:
            error = "The URL you entered did not match. No data was deleted."

    return render(request, "account_delete.html", {
        "user_url": user_url,
        "error": error,
    })


# --- Broadcast Views ---


def _is_admin(request):
    return request.session.get("user_url", "") in settings.PADD_ADMIN_URLS


def admin_view(request):
    if not _is_admin(request):
        return HttpResponse(status=403)

    broadcasts = Broadcast.objects.all()

    users = KnownUser.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        users = users.filter(Q(name__icontains=q) | Q(url__icontains=q))

    paginator = Paginator(users, 25)
    page_number = request.GET.get("page")
    users_page = paginator.get_page(page_number)

    return render(request, "admin.html", {
        "broadcasts": broadcasts,
        "users_page": users_page,
        "q": q,
    })


def broadcast_create_view(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    if not _is_admin(request):
        return HttpResponse(status=403)

    message = request.POST.get("message", "").strip()
    if message:
        Broadcast.objects.create(message=message)

    return redirect("admin")


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
    return redirect("admin")


def broadcast_dismiss_view(request, broadcast_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    user_url = request.session.get("user_url", "")
    if user_url:
        DismissedBroadcast.objects.get_or_create(
            user_url=user_url, broadcast_id=broadcast_id
        )

    return HttpResponse("")


def broadcast_banner_view(request):
    """Returns the broadcast banner partial for HTMX polling."""
    return render(request, "partials/broadcast_banner.html")


# --- Discover View ---


def discover_view(request):
    if not request.session.get("access_token"):
        return redirect("login")

    endpoint = request.session.get("microsub_endpoint")
    token = request.session.get("access_token")
    try:
        channels = api.get_channels(endpoint, token)
    except api.MicrosubError:
        channels = []

    sort = request.GET.get("sort", "hot")

    entries = CachedEntry.objects.annotate(
        like_count=Count("interactions", filter=Q(interactions__kind="like")),
        repost_count=Count("interactions", filter=Q(interactions__kind="repost")),
        reply_count=Count("interactions", filter=Q(interactions__kind="reply")),
        total_interactions=Count("interactions"),
        last_interaction=Max("interactions__created_at"),
    ).filter(total_interactions__gt=0)

    if sort == "new":
        entries = entries.order_by("-last_interaction")
    else:  # "hot" default
        entries = entries.order_by("-total_interactions", "-last_interaction")

    paginator = Paginator(entries, 25)
    page = paginator.get_page(request.GET.get("page", 1))

    return render(request, "discover.html", {
        "entries": page,
        "sort": sort,
        "channels": channels,
        "has_micropub": bool(request.session.get("micropub_endpoint")),
    })
