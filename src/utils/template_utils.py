"""Template utility functions for BBCode generation."""

import sqlite3
from src.storage.database import QueueStore
from src.utils.logger import log


def get_file_host_links_for_template(queue_store: QueueStore, gallery_path: str) -> str:
    """Get file host download URLs for BBCode template placeholder.

    Args:
        queue_store: Database instance
        gallery_path: Gallery folder path

    Returns:
        Newline-separated download URLs, or empty string if none exist.
        Empty string (not "N/A") enables conditional template logic:
        [if hostLinks]Download: #hostLinks#[/if]

    Example:
        https://rapidgator.net/file/abc123
        https://tezfiles.com/file/xyz789
        https://keep2share.cc/file/def456
    """
    try:
        uploads = queue_store.get_file_host_uploads(gallery_path)
        log(f"Found {len(uploads)} file host upload records for gallery",
            level="debug", category="template")

        # Filter: only completed uploads with valid download URLs
        urls = [
            u['download_url']
            for u in uploads
            if u['status'] == 'completed'
            and u['download_url']
            and u['download_url'].strip()
        ]

        log(f"Filtered to {len(urls)} completed uploads with valid URLs",
            level="debug", category="template")

        return "\n".join(urls) if urls else ""

    except (sqlite3.Error, OSError, KeyError) as e:
        log(f"Failed to retrieve file host links: {e}",
            level="warning", category="template")
        return ""
