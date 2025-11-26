"""
Artifact finder utility for locating gallery JSON and BBCode files by gallery ID.
"""
import os
import glob
from typing import Optional


def find_gallery_json_by_id(gallery_id: str, gallery_path: Optional[str] = None) -> Optional[str]:
    """
    Find JSON artifact file by gallery ID pattern (*_{gallery_id}.json).

    Args:
        gallery_id: The gallery ID to search for (e.g., "1gq6n")
        gallery_path: Optional path to check for .uploaded subfolder first

    Returns:
        Path to JSON file if found, None otherwise.
        Prefers .uploaded location if both exist.
    """
    if not gallery_id:
        return None

    search_locations = []

    # Check .uploaded subfolder first if gallery_path provided
    if gallery_path:
        uploaded_dir = os.path.join(gallery_path, ".uploaded")
        if os.path.exists(uploaded_dir):
            search_locations.append(uploaded_dir)

    # Check central storage
    try:
        from imxup import get_central_storage_path
        central_path = get_central_storage_path()
        if os.path.exists(central_path):
            search_locations.append(central_path)
    except (ImportError, Exception):
        # Fallback to hardcoded path if imports fail
        home = os.path.expanduser("~")
        fallback_central = os.path.join(home, ".imxup", "galleries")
        if os.path.exists(fallback_central):
            search_locations.append(fallback_central)

    # Search for files matching the pattern
    for location in search_locations:
        pattern = os.path.join(location, f"*_{gallery_id}.json")
        matches = glob.glob(pattern)
        if matches:
            # Return the first match (most recent if multiple exist)
            return sorted(matches, key=os.path.getmtime, reverse=True)[0]

    return None