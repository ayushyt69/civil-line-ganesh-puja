#!/usr/bin/env python3
"""Create concise public updates only when visitor-facing content changes."""

from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import subprocess
import difflib

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "data" / "puja-updates.json"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}


class VisibleContent(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden_depth += 1
        if tag == "img":
            attrs = dict(attrs)
            src = attrs.get("src", "").strip()
            alt = attrs.get("alt", "").strip()
            if src:
                self.parts.append("IMAGE:" + src + ":" + alt)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data):
        if not self.hidden_depth:
            clean = " ".join(data.split())
            if clean:
                self.parts.append(clean)


def public_signature(html):
    parser = VisibleContent()
    parser.feed(html)
    return " ".join(parser.parts)


def read_at(revision, path):
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=ROOT, text=True, capture_output=True
    )
    return result.stdout if result.returncode == 0 else ""


def changed_paths(before, after):
    result = subprocess.run(
        ["git", "diff", "--name-status", before, after],
        cwd=ROOT, text=True, capture_output=True, check=True
    )
    changed = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2:
            changed.append((fields[0], fields[-1]))
    return changed


def make_messages(before, after, changes):
    messages = []
    changed_files = {path for _, path in changes}

    # A changed image in the gallery is directly visible to visitors.
    gallery_images = [
        path for path in changed_files
        if path.startswith("assets/gallery/") and Path(path).suffix.lower() in IMAGE_SUFFIXES
    ]
    if gallery_images:
        messages.append("Puja photo gallery updated.")

    # Check actual rendered text/image references, not merely file timestamps.
    page_messages = {
        "gallery.html": "Photo gallery page updated.",
        "memory-vault.html": "2026 celebration memories updated.",
        "maintenance.html": "Website information updated.",
    }
    for path, message in page_messages.items():
        if path in changed_files:
            old = public_signature(read_at(before, path))
            new = public_signature(read_at(after, path))
            if old != new and message not in messages:
                messages.append(message)

    if "index.html" in changed_files:
        old = public_signature(read_at(before, "index.html"))
        new = public_signature(read_at(after, "index.html"))
        if old != new:
            changed_words = " ".join(
                line[2:] for line in difflib.ndiff(old.split(), new.split())
                if line.startswith(("+ ", "- "))
            ).lower()
            if any(word in changed_words for word in ("donation", "donate", "chanda", "upi", "contribution")):
                message = "Donation information updated."
            elif any(word in changed_words for word in ("committee", "member", "president")):
                message = "Committee information updated."
            elif any(word in changed_words for word in ("event", "puja", "aarti", "schedule", "ganesh")):
                message = "Puja information updated."
            else:
                message = "Website content updated."
            messages.append(message)

    # Other public image assets can change the appearance of the live site.
    other_images = [
        path for path in changed_files
        if path.startswith("assets/") and path not in gallery_images
        and Path(path).suffix.lower() in IMAGE_SUFFIXES
    ]
    if other_images:
        messages.append("Website photos and visuals refreshed.")

    # Keep the feed concise and avoid duplicate lines for the same push.
    return list(dict.fromkeys(messages))[:4]


def main():
    before = os.environ.get("BEFORE_SHA", "")
    after = os.environ.get("AFTER_SHA", "HEAD")
    if not before or set(before) == {"0"}:
        print("Initial push: no previous revision to compare.")
        return

    changes = changed_paths(before, after)
    messages = make_messages(before, after, changes)
    if not messages:
        print("No visitor-facing content changes detected; feed left untouched.")
        return

    FEED.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(FEED.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata"))
    stamp = now.isoformat(timespec="minutes")
    additions = [{"message": message, "date": stamp} for message in messages]
    FEED.write_text(
        json.dumps((additions + existing)[:12], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )
    print("Published updates:", "; ".join(messages))


if __name__ == "__main__":
    main()
