"""
Core upload engine shared by CLI and GUI.

This module centralizes the upload loop, retries, and statistics aggregation,
so both the CLI (`imxup.py`) and GUI (`imxup_gui.py`) can use the same logic
without duplication.
"""

from __future__ import annotations

import os
import time
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re
import sys
from functools import cmp_to_key
import ctypes
from typing import Callable, Iterable, Optional, Tuple, List, Dict, Any, Set


ProgressCallback = Callable[[int, int, int, str], None]
LogCallback = Callable[[str], None]
SoftStopCallback = Callable[[], bool]
ImageUploadedCallback = Callable[[str, Dict[str, Any], int], None]


class UploadEngine:
    """Shared engine for uploading a folder as an imx.to gallery.

    The engine expects an `uploader` object that implements:
      - upload_image(image_path, create_gallery=False, gallery_id=None, thumbnail_size=..., thumbnail_format=...)
      - create_gallery_with_name(gallery_name, public_gallery, skip_login=True)
      - attributes: web_url (for links)
    """

    def __init__(self, uploader: Any):
        self.uploader = uploader

    def run(
        self,
        folder_path: str,
        gallery_name: Optional[str],
        thumbnail_size: int,
        thumbnail_format: int,
        max_retries: int,
        public_gallery: int,
        parallel_batch_size: int,
        template_name: str,
        # Resume support from GUI; pass empty for CLI
        already_uploaded: Optional[Set[str]] = None,
        # Callbacks (all optional)
        on_progress: Optional[ProgressCallback] = None,
        on_log: Optional[LogCallback] = None,
        should_soft_stop: Optional[SoftStopCallback] = None,
        on_image_uploaded: Optional[ImageUploadedCallback] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        # Gather image files
        def _natural_sort_key(name: str):
            parts = re.split(r"(\d+)", name)
            key = []
            for p in parts:
                if p.isdigit():
                    try:
                        key.append(int(p))
                    except Exception:
                        key.append(p)
                else:
                    key.append(p.lower())
            return tuple(key)
        
        def _explorer_sort(names: List[str]) -> List[str]:
            """Windows Explorer (StrCmpLogicalW) ordering; fallback to natural sort on non-Windows."""
            if sys.platform != "win32":
                return sorted(names, key=_natural_sort_key)
            try:
                _cmp = ctypes.windll.shlwapi.StrCmpLogicalW
                _cmp.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
                _cmp.restype = ctypes.c_int
                return sorted(names, key=cmp_to_key(lambda a, b: _cmp(a, b)))
            except Exception:
                return sorted(names, key=_natural_sort_key)
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif')
        all_image_files: List[str] = _explorer_sort([
            f for f in os.listdir(folder_path)
            if f.lower().endswith(image_extensions) and os.path.isfile(os.path.join(folder_path, f))
        ])
        if not all_image_files:
            raise ValueError(f"No image files found in {folder_path}")

        # Resume: exclude already-uploaded files
        already_uploaded = already_uploaded or set()
        image_files: List[str] = [f for f in all_image_files if f not in already_uploaded]

        original_total_images = len(all_image_files)

        # Fast pre-scan: only compute total size to avoid startup delay
        # Dimension sampling (if needed) is deferred until after uploads complete
        image_dimensions_map: Dict[str, Tuple[int, int]] = {}
        total_size = 0
        for f in all_image_files:
            fp = os.path.join(folder_path, f)
            try:
                total_size += os.path.getsize(fp)
            except OSError:
                pass

        # Determine gallery name
        if not gallery_name:
            gallery_name = os.path.basename(folder_path)
        # Sanitize gallery name using the canonical helper (lazy import to avoid circular deps)
        try:
            from imxup import sanitize_gallery_name  # type: ignore
            original_name = gallery_name
            gallery_name = sanitize_gallery_name(gallery_name)
            if on_log and original_name != gallery_name:
                on_log(f"Sanitized gallery name: '{original_name}' -> '{gallery_name}'")
        except Exception:
            # Best-effort; if unavailable, proceed with provided name
            pass

        # Always create gallery via API by uploading the first image (faster, avoids web login delays)
        gallery_id: Optional[str] = None
        initial_completed = 0
        initial_uploaded_size = 0
        preseed_images: List[Dict[str, Any]] = []
        files_to_upload: List[str]
        # Upload first image to create gallery via API
        first_file = image_files[0]
        first_image_path = os.path.join(folder_path, first_file)
        if on_log:
            on_log(f"Uploading first image to create gallery: {first_file}")
        first_response = self.uploader.upload_image(
            first_image_path,
            create_gallery=True,
            thumbnail_size=thumbnail_size,
            thumbnail_format=thumbnail_format,
        )
        if first_response.get('status') != 'success':
            raise Exception(f"Failed to create gallery: {first_response}")
        gallery_id = first_response['data'].get('gallery_id')
        preseed_images = [first_response['data']]
        # Log first image success with URL
        if on_log:
            try:
                first_url = first_response['data'].get('image_url', '')
                on_log(f"✓ [{gallery_id}] {first_file} uploaded successfully ({first_url})")
            except Exception:
                pass
        initial_completed = 1
        try:
            initial_uploaded_size = os.path.getsize(first_image_path)
        except Exception:
            initial_uploaded_size = 0
        # Report the first image upload so GUI resume/merge includes it
        if on_image_uploaded:
            try:
                on_image_uploaded(first_file, first_response['data'], initial_uploaded_size)
            except Exception:
                pass
        # Attempt immediate rename if a web session exists; otherwise record for later auto-rename
        try:
            last_method = getattr(self.uploader, 'last_login_method', None)
        except Exception:
            last_method = None
        if gallery_name and last_method in ('cookies', 'credentials'):
            try:
                rename_ok = getattr(self.uploader, 'rename_gallery_with_session', lambda *_: False)(gallery_id, gallery_name)
                if rename_ok:
                    if on_log:
                        on_log(f"Renamed gallery immediately using web session: '{gallery_name}'")
                else:
                    # Web session present but rename failed; queue for auto-rename later
                    try:
                        from imxup import save_unnamed_gallery  # type: ignore
                        save_unnamed_gallery(gallery_id, gallery_name)
                        if on_log:
                            on_log(f"Queued gallery for auto-rename: '{gallery_name}'")
                    except Exception:
                        pass
            except Exception:
                # On error, also queue for later rename so it doesn't slip past
                try:
                    from imxup import save_unnamed_gallery  # type: ignore
                    save_unnamed_gallery(gallery_id, gallery_name)
                except Exception:
                    pass
        else:
            # No web session; save for later auto-rename
            try:
                from imxup import save_unnamed_gallery  # type: ignore
                save_unnamed_gallery(gallery_id, gallery_name)
            except Exception:
                pass
        # Emit an initial progress update
        if on_progress:
            percent_once = int((initial_completed / max(original_total_images, 1)) * 100)
            on_progress(initial_completed, original_total_images, percent_once, first_file)
        files_to_upload = image_files[1:]

        gallery_url = f"https://imx.to/g/{gallery_id}"

        # Container for results
        results: Dict[str, Any] = {
            'gallery_url': gallery_url,
            'images': list(preseed_images),
        }

        def upload_single_image(image_file: str) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
            image_path = os.path.join(folder_path, image_file)
            try:
                response = self.uploader.upload_image(
                    image_path,
                    gallery_id=gallery_id,
                    thumbnail_size=thumbnail_size,
                    thumbnail_format=thumbnail_format,
                )
                if response.get('status') == 'success':
                    return image_file, response['data'], None
                return image_file, None, f"API error: {response}"
            except Exception as e:
                return image_file, None, f"Network error: {e}"

        # Concurrency loop
        uploaded_images: List[Tuple[str, Dict[str, Any]]] = []
        failed_images: List[Tuple[str, str]] = []
        file_position = {fname: idx for idx, fname in enumerate(all_image_files)}

        def maybe_soft_stopping() -> bool:
            return bool(should_soft_stop and should_soft_stop())

        with ThreadPoolExecutor(max_workers=parallel_batch_size) as executor:
            remaining: List[str] = list(files_to_upload)
            futures_map: Dict[concurrent.futures.Future, str] = {}
            # Prime pool
            for _ in range(min(parallel_batch_size, len(remaining))):
                img = remaining.pop(0)
                futures_map[executor.submit(upload_single_image, img)] = img

            while futures_map:
                done, _ = concurrent.futures.wait(list(futures_map.keys()), return_when=concurrent.futures.FIRST_COMPLETED)
                for fut in done:
                    img = futures_map.pop(fut)
                    image_file, image_data, error = fut.result()
                    if image_data:
                        uploaded_images.append((image_file, image_data))
                        # Per-image success log (categorized)
                        if on_log:
                            try:
                                img_url = image_data.get('image_url', '')
                                on_log(f"[uploads:file] ✓ [{gallery_id}] {image_file} uploaded successfully ({img_url})")
                            except Exception:
                                pass
                        # Per-image callback for resume-aware consumers
                        if on_image_uploaded:
                            try:
                                size_bytes = os.path.getsize(os.path.join(folder_path, image_file))
                            except Exception:
                                size_bytes = 0
                            on_image_uploaded(image_file, image_data, size_bytes)
                    else:
                        failed_images.append((image_file, error or "unknown error"))
                    # Progress
                    completed_count = initial_completed + len(uploaded_images)
                    if on_progress:
                        percent = int((completed_count / max(original_total_images, 1)) * 100)
                        on_progress(completed_count, original_total_images, percent, image_file)
                    # Queue next if not soft-stopping
                    if remaining and not maybe_soft_stopping():
                        nxt = remaining.pop(0)
                        futures_map[executor.submit(upload_single_image, nxt)] = nxt

        # Retries
        retry_count = 0
        while failed_images and retry_count < max_retries and not maybe_soft_stopping():
            retry_count += 1
            retry_failed: List[Tuple[str, str]] = []
            if on_log:
                on_log(f"[uploads] Retrying {len(failed_images)} failed uploads (attempt {retry_count}/{max_retries})")
            with ThreadPoolExecutor(max_workers=parallel_batch_size) as executor:
                remaining = [img for img, _ in failed_images]
                futures_map = {executor.submit(upload_single_image, img): img for img in remaining[:parallel_batch_size]}
                remaining = remaining[parallel_batch_size:]
                while futures_map:
                    done, _ = concurrent.futures.wait(list(futures_map.keys()), return_when=concurrent.futures.FIRST_COMPLETED)
                    for fut in done:
                        img = futures_map.pop(fut)
                        image_file, image_data, error = fut.result()
                        if image_data:
                            uploaded_images.append((image_file, image_data))
                            if on_image_uploaded:
                                try:
                                    size_bytes = os.path.getsize(os.path.join(folder_path, image_file))
                                except Exception:
                                    size_bytes = 0
                                on_image_uploaded(image_file, image_data, size_bytes)
                            # Per-image success log (retry path)
                            if on_log:
                                try:
                                    img_url = image_data.get('image_url', '')
                                    on_log(f"[uploads:file] ✓ [{gallery_id}] {image_file} uploaded successfully ({img_url})")
                                except Exception:
                                    pass
                            if on_log:
                                on_log(f"[uploads] Retry successful: {image_file}")
                        else:
                            retry_failed.append((image_file, error or "unknown error"))
                            if on_log:
                                on_log(f"Retry failed: {image_file} - {error}")
                        completed_count = initial_completed + len(uploaded_images)
                        if on_progress:
                            percent = int((completed_count / max(original_total_images, 1)) * 100)
                            on_progress(completed_count, original_total_images, percent, image_file)
                        if remaining:
                            nxt = remaining.pop(0)
                            futures_map[executor.submit(upload_single_image, nxt)] = nxt
            failed_images = retry_failed

        # Sort by original order
        uploaded_images.sort(key=lambda x: file_position.get(x[0], 10**9))
        for _, image_data in uploaded_images:
            results['images'].append(image_data)

        # Stats
        end_time = time.time()
        upload_time = end_time - start_time
        try:
            uploaded_size = initial_uploaded_size + sum(
                os.path.getsize(os.path.join(folder_path, img_file)) for img_file, _ in uploaded_images
            )
        except Exception:
            uploaded_size = 0
        transfer_speed = uploaded_size / upload_time if upload_time > 0 else 0

        # Dimensions (lazy, sampled to avoid blocking start)
        try:
            successful_filenames: List[str] = []
            if initial_completed == 1 and preseed_images:
                successful_filenames.append(all_image_files[0])
            for img_file, _ in uploaded_images:
                successful_filenames.append(img_file)
            # Sample up to N files for dimension computation
            MAX_DIM_SAMPLES = 25
            sampled_dims: List[Tuple[int, int]] = []
            from itertools import islice
            for fname in islice(successful_filenames, 0, MAX_DIM_SAMPLES):
                fp = os.path.join(folder_path, fname)
                try:
                    from PIL import Image  # lazy import
                    with Image.open(fp) as img:
                        w, h = img.size
                        sampled_dims.append((w, h))
                except Exception:
                    continue
            avg_width = sum(w for w, h in sampled_dims) / len(sampled_dims) if sampled_dims else 0
            avg_height = sum(h for w, h in sampled_dims) / len(sampled_dims) if sampled_dims else 0
            max_width = max((w for w, h in sampled_dims), default=0)
            max_height = max((h for w, h in sampled_dims), default=0)
            min_width = min((w for w, h in sampled_dims), default=0)
            min_height = min((h for w, h in sampled_dims), default=0)
        except Exception:
            avg_width = avg_height = max_width = max_height = min_width = min_height = 0

        # Attach filename and optional dims/sizes to each image entry for richer JSON (CLI parity)
        dims_by_name = image_dimensions_map
        for idx, (fname, data) in enumerate(uploaded_images):
            try:
                size_bytes = os.path.getsize(os.path.join(folder_path, fname))
            except Exception:
                size_bytes = 0
            w, h = dims_by_name.get(fname, (0, 0))
            try:
                base, ext = os.path.splitext(fname)
                fname_norm = base + ext.lower()
            except Exception:
                fname_norm = fname
            # Ensure thumb_url if missing
            t = data.get('thumb_url')
            if not t and data.get('image_url'):
                try:
                    parts = data.get('image_url').split('/i/')
                    if len(parts) == 2 and parts[1]:
                        img_id = parts[1].split('/')[0]
                        _, ext = os.path.splitext(fname_norm)
                        ext_use = (ext.lower() or '.jpg') if ext else '.jpg'
                        t = f"https://imx.to/u/t/{img_id}{ext_use}"
                except Exception:
                    pass
            data.setdefault('thumb_url', t)
            data.setdefault('original_filename', fname_norm)
            data.setdefault('width', w)
            data.setdefault('height', h)
            data.setdefault('size_bytes', size_bytes)
        # Also enrich the preseed (first) image if present in results
        try:
            if preseed_images:
                first_data = preseed_images[0]
                fname = all_image_files[0]
                try:
                    size_bytes = os.path.getsize(os.path.join(folder_path, fname))
                except Exception:
                    size_bytes = 0
                w, h = dims_by_name.get(fname, (0, 0))
                try:
                    base, ext = os.path.splitext(fname)
                    fname_norm = base + (ext.lower() if ext else '')
                except Exception:
                    fname_norm = fname
                t = first_data.get('thumb_url')
                if not t and first_data.get('image_url'):
                    try:
                        parts = first_data.get('image_url').split('/i/')
                        if len(parts) == 2 and parts[1]:
                            img_id = parts[1].split('/')[0]
                            _, ext = os.path.splitext(fname_norm)
                            ext_use = (ext.lower() or '.jpg') if ext else '.jpg'
                            t = f"https://imx.to/u/t/{img_id}{ext_use}"
                    except Exception:
                        pass
                first_data.setdefault('thumb_url', t)
                first_data.setdefault('original_filename', fname_norm)
                first_data.setdefault('width', w)
                first_data.setdefault('height', h)
                first_data.setdefault('size_bytes', size_bytes)
        except Exception:
            pass

        results.update({
            'gallery_id': gallery_id,
            'gallery_name': gallery_name,
            'upload_time': upload_time,
            'total_size': total_size,
            'uploaded_size': uploaded_size,
            'transfer_speed': transfer_speed,
            'avg_width': avg_width,
            'avg_height': avg_height,
            'max_width': max_width,
            'max_height': max_height,
            'min_width': min_width,
            'min_height': min_height,
            'successful_count': initial_completed + len(uploaded_images),
            'failed_count': len(failed_images),
            'failed_details': failed_images,
            # echo settings for artifact helper
            'thumbnail_size': thumbnail_size,
            'thumbnail_format': thumbnail_format,
            'public_gallery': public_gallery,
            'parallel_batch_size': parallel_batch_size,
            'template_name': template_name,
            'total_images': original_total_images,
            'started_at': datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M:%S'),
        })

        # Emit consolidated success at gallery level when appropriate
        if on_log:
            try:
                total_attempted = len(all_image_files)
                if failed_images:
                    on_log(f"[uploads] ✗ Gallery '{gallery_id}' completed with failures in {upload_time:.1f}s ({results['successful_count']}/{total_attempted} images)")
                    for fname, reason in failed_images:
                        on_log(f"[uploads] ✗ {fname}: {reason}")
                else:
                    # Include gallery name and link for clarity
                    try:
                        gname = results.get('gallery_name') or gallery_name
                    except Exception:
                        gname = gallery_name
                    on_log(
                        f"[uploads:gallery] ✓ Uploaded {results['successful_count']} images ({int(uploaded_size)/(1024*1024):.1f} MiB) in {upload_time:.1f}s: {gname} -> {gallery_url}"
                    )
            except Exception:
                pass

        return results


