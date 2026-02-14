from django.db import models


class CachedEntry(models.Model):
    url = models.URLField(max_length=2048, unique=True)
    author_name = models.CharField(max_length=255, blank=True, default="")
    author_url = models.URLField(max_length=2048, blank=True, default="")
    title = models.CharField(max_length=512, blank=True, default="")
    first_seen = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title or self.url


class Interaction(models.Model):
    class Kind(models.TextChoices):
        LIKE = "like", "Like"
        REPLY = "reply", "Reply"
        REPOST = "repost", "Repost"

    user_url = models.URLField(max_length=2048, db_index=True)
    entry = models.ForeignKey(
        CachedEntry, on_delete=models.CASCADE, related_name="interactions"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    content = models.TextField(blank=True, default="")
    result_url = models.URLField(max_length=2048, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user_url", "entry", "kind")]

    def __str__(self):
        return f"{self.kind} of {self.entry.url} by {self.user_url}"
