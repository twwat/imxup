import os
import zipfile
import tempfile
import time
from pathlib import Path

def zip_folder(folder_path, output_path=None, compression='store'):
    """
    Zip a folder, prioritizing speed over compression.

    Args:
        folder_path (str): Path to the folder to zip
        output_path (str, optional): Output zip file path. If None, uses folder name + .zip
        compression (str): Compression mode - 'store' (no compression, fast) or 'deflate' (compressed)

    Returns:
        str: Path to the created zip file
    """
    if not os.path.exists(folder_path):
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    if not os.path.isdir(folder_path):
        raise ValueError(f"Path is not a directory: {folder_path}")

    folder_path = Path(folder_path)

    if output_path is None:
        output_path = f"{folder_path}.zip"

    # Remove .zip extension if present to avoid double extension
    if str(output_path).endswith('.zip'):
        output_path = str(output_path)[:-4] + '.zip'
    else:
        output_path = str(output_path) + '.zip'

    # Determine compression type
    if compression == 'store':
        compress_type = zipfile.ZIP_STORED  # No compression - maximum speed
    else:
        compress_type = zipfile.ZIP_DEFLATED  # Compression

    # Create ZIP file manually for better control over compression
    with zipfile.ZipFile(output_path, 'w', compress_type) as zipf:
        for file_path in folder_path.rglob('*'):
            if file_path.is_file():
                # Get the relative path for the archive
                arcname = file_path.relative_to(folder_path.parent)
                zipf.write(file_path, arcname)

    return output_path


def create_temp_zip(folder_path):
    """
    Create a temporary ZIP file of a folder in the system temp directory.
    Uses store mode (no compression) for maximum speed.

    Args:
        folder_path (str): Path to the folder to zip

    Returns:
        str: Path to the created temporary zip file
    """
    folder_path = Path(folder_path)
    folder_name = folder_path.name

    # Create temp file with clean gallery name (no prefix - temp dir indicates it's temporary)
    temp_dir = tempfile.gettempdir()
    temp_zip_path = os.path.join(temp_dir, f"{folder_name}.zip")

    # Remove existing temp file if it exists
    if os.path.exists(temp_zip_path):
        try:
            os.remove(temp_zip_path)
        except (OSError, PermissionError):
            # If we can't remove it, create a new unique name with timestamp
            temp_zip_path = os.path.join(temp_dir, f"{folder_name}_{int(time.time())}.zip")

    return zip_folder(folder_path, temp_zip_path[:-4], compression='store')