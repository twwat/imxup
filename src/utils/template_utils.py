"""Template utility functions for BBCode generation."""

import sqlite3
from src.storage.database import QueueStore
from src.utils.logger import log


def get_file_host_links_for_template(queue_store: QueueStore, gallery_path: str) -> str:
    """Get file host download URLs for BBCode template placeholder.

    Applies per-host BBCode formatting if configured, otherwise returns raw URLs.

    Args:
        queue_store: Database instance
        gallery_path: Gallery folder path

    Returns:
        Newline-separated download URLs (formatted or raw), or empty string if none exist.
        Empty string (not "N/A") enables conditional template logic:
        [if hostLinks]Download: #hostLinks#[/if]

    Example (raw URLs):
        https://rapidgator.net/file/abc123
        https://tezfiles.com/file/xyz789

    Example (with BBCode format "[url=#link#]#hostName#[/url]"):
        [url=https://rapidgator.net/file/abc123]Rapidgator[/url]
        [url=https://tezfiles.com/file/xyz789]TezFiles[/url]
    """
    from src.core.file_host_config import get_file_host_setting, get_config_manager

    try:
        uploads = queue_store.get_file_host_uploads(gallery_path)
        log(f"Found {len(uploads)} file host upload records for gallery",
            level="debug", category="template")

        config_manager = get_config_manager()

        formatted_links = []
        for u in uploads:
            if u['status'] != 'completed' or not u['download_url'] or not u['download_url'].strip():
                continue

            host_id = u['host_name']
            download_url = u['download_url'].strip()

            # Check for BBCode format setting
            bbcode_format = get_file_host_setting(host_id, 'bbcode_format', 'str')

            if bbcode_format:
                # Get host display name
                host_config = config_manager.hosts.get(host_id)
                host_name = host_config.name if host_config else host_id.capitalize()

                # Apply format - replace placeholders
                formatted = bbcode_format.replace('#link#', download_url)
                formatted = formatted.replace('#hostName#', host_name)
                formatted_links.append(formatted)
            else:
                # No format - use raw URL
                formatted_links.append(download_url)

        log(f"Filtered to {len(formatted_links)} completed uploads with valid URLs",
            level="debug", category="template")

        return "\n".join(formatted_links) if formatted_links else ""

    except (sqlite3.Error, OSError, KeyError) as e:
        log(f"Failed to retrieve file host links: {e}",
            level="warning", category="template")
        return ""
