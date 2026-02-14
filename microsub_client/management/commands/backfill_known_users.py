from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from microsub_client.models import KnownUser


class Command(BaseCommand):
    help = "Backfill KnownUser records from existing sessions"

    def handle(self, *args, **options):
        now = timezone.now()
        sessions = Session.objects.filter(expire_date__gt=now)
        created = 0
        updated = 0

        for session in sessions:
            data = session.get_decoded()
            user_url = data.get("user_url")
            if not user_url:
                continue

            _, was_created = KnownUser.objects.update_or_create(
                url=user_url,
                defaults={
                    "name": data.get("user_name", ""),
                    "photo": data.get("user_photo", ""),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated"
            )
        )
