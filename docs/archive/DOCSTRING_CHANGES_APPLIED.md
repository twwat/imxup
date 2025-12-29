# Docstring Changes Applied to engine.py

## Summary

This document tracks the enhanced docstrings that should be applied to H:/IMXuploader/src/core/engine.py

## Changes to Apply

### 1. Module-Level Docstring (Lines 1-7)

**Current:**
```python
"""
Core upload engine shared by CLI and GUI.

This module centralizes the upload loop, retries, and statistics aggregation,
so both the CLI (`imxup.py`) and GUI (`imxup_gui.py`) can use the same logic
without duplication.
"""
```

**Enhanced (to replace):**
```python
"""
Core upload engine shared by CLI and GUI.

This module centralizes the upload loop, retries, and statistics aggregation,
so both the CLI (`imxup.py`) and GUI (`imxup_gui.py`) can use the same logic
without duplication.

Architecture:
    - UploadEngine: Main orchestrator for gallery uploads
    - AtomicCounter: Thread-safe progress tracking across workers
    - ByteCountingCallback: pycurl integration for upload progress

Upload Workflow:
    1. Scan folder for images (natural Windows Explorer sort)
    2. Create gallery by uploading first image (faster than web login)
    3. Upload remaining images concurrently with ThreadPoolExecutor
    4. Retry failed uploads with exponential backoff
    5. Collect statistics and generate report

Performance Features:
    - Concurrent uploads with configurable batch size
    - Thread-local HTTP sessions for connection reuse
    - Minimal file I/O during upload (size calculated upfront)
    - Deferred dimension calculation (uses precalculated values)

Resume Support:
    - Skip already-uploaded files via set comparison
    - Append to existing gallery ID
    - Merge metadata from previous sessions
"""
```

### 2. AtomicCounter Class Docstring (Line 28)

**Current:**
```python
"""Thread-safe byte counter for tracking upload progress across multiple threads."""
```

**Enhanced (to replace):**
```python
"""Thread-safe byte counter for tracking upload progress across multiple threads.

This class uses a simple lock-based approach to provide atomic operations
on a shared integer value. Used by the upload engine to track bytes transferred
across concurrent upload workers.

The counter is designed for high-frequency updates from multiple threads without
data races or corruption.

Attributes:
    _value: Internal byte count (protected by lock).
    _lock: Threading lock for atomic operations.

Example:
    >>> counter = AtomicCounter()
    >>> counter.add(1024)  # Add 1KB
    >>> print(counter.get())  # Read current value
    1024
    >>> counter.reset()  # Reset to zero
"""
```

### 3. AtomicCounter.__init__ (Line 30)

**Add:**
```python
"""Initialize counter with zero value and a new lock."""
```

### 4. AtomicCounter.add (Line 34)

**Current:**
```python
"""Add bytes to counter (thread-safe)."""
```

**Enhanced (to replace):**
```python
"""Add bytes to counter (thread-safe).

Args:
    amount: Number of bytes to add (must be non-negative).
"""
```

### 5. AtomicCounter.get (Line 39)

**Current:**
```python
"""Get current value (thread-safe)."""
```

**Enhanced (to replace):**
```python
"""Get current value (thread-safe).

Returns:
    Current byte count.
"""
```

### 6. ByteCountingCallback Class Docstring (Line 50)

**Current:**
```python
"""Callback wrapper that tracks upload progress deltas and updates global counter."""
```

**Enhanced (to replace):**
```python
"""Callback wrapper that tracks upload progress deltas and updates global counter.

This class implements the pycurl progress callback interface, calculating
the incremental bytes transferred since the last call and updating the
global counter accordingly.

The callback is invoked by pycurl during upload transmission to report
progress. It computes the delta between calls to avoid double-counting.

Attributes:
    global_counter: Shared AtomicCounter tracking bytes across all uploads.
    last_bytes: Last reported bytes_read value for delta calculation.

Example:
    >>> global_counter = AtomicCounter()
    >>> callback = ByteCountingCallback(global_counter)
    >>> # pycurl calls callback(1024, 10240) when 1KB of 10KB uploaded
"""
```

### 7. ByteCountingCallback.__init__ (Lines 52-61)

**Current:**
```python
"""Initialize with optional global counter.

Args:
    global_counter: Tracks bytes across ALL galleries (used by Speed box)
    gallery_counter: Ignored (per-gallery tracking removed)
    worker_thread: Ignored (not needed)
"""
```

**Enhanced (to replace):**
```python
"""Initialize with optional counters.

Args:
    global_counter: Tracks bytes across ALL galleries (used by Speed box).
    gallery_counter: Ignored (per-gallery tracking removed).
    worker_thread: Ignored (not needed).
"""
```

### 8. ByteCountingCallback.__call__ (Line 66)

**Current:**
```python
"""Called by pycurl during upload transmission."""
```

**Enhanced (to replace):**
```python
"""Called by pycurl during upload transmission.

Calculates the delta since last call and updates the global counter.

Args:
    bytes_read: Total bytes uploaded so far for this file.
    total_size: Total file size in bytes.
"""
```

### 9. Type Aliases (Lines 74-76)

**Current:**
```python
# Type aliases for callbacks
ProgressCallback = Callable[[int, int, int, str], None]
SoftStopCallback = Callable[[], bool]
ImageUploadedCallback = Callable[[str, Dict[str, Any], int], None]
```

**Enhanced (to replace):**
```python
# Type aliases for callbacks
ProgressCallback = Callable[[int, int, int, str], None]  # (completed, total, percent, current_file)
SoftStopCallback = Callable[[], bool]  # Returns True if upload should stop
ImageUploadedCallback = Callable[[str, Dict[str, Any], int], None]  # (filename, image_data, size_bytes)
```

### 10. UploadEngine Class Docstring (Lines 80-86)

**Current:**
```python
"""Shared engine for uploading a folder as an imx.to gallery.

The engine expects an `uploader` object that implements:
  - upload_image(image_path, create_gallery=False, gallery_id=None, thumbnail_size=..., thumbnail_format=...)
  - create_gallery_with_name(gallery_name, skip_login=True)
  - attributes: web_url (for links)
"""
```

**Enhanced (to replace):**
```python
"""Shared engine for uploading a folder as an imx.to gallery.

This class orchestrates the entire upload workflow including:
- Folder scanning and image discovery
- Gallery creation via API
- Concurrent image uploads with retry logic
- Progress tracking and statistics collection
- Resume/append support for interrupted uploads

The engine expects an `uploader` object that implements:
  - upload_image(image_path, create_gallery=False, gallery_id=None,
                 thumbnail_size=..., thumbnail_format=...)
  - create_gallery_with_name(gallery_name, skip_login=True)
  - attributes: web_url (for links)

Upload Strategy:
    1. First image creates gallery (faster than web login)
    2. Remaining images uploaded concurrently
    3. Failed images retried with exponential backoff
    4. Statistics collected and returned

Concurrency Model:
    - ThreadPoolExecutor with configurable worker count
    - Thread-local HTTP sessions for connection reuse
    - Lock-free progress tracking via AtomicCounter
    - Graceful shutdown via soft_stop callback

Attributes:
    uploader: Uploader instance implementing required methods.
    rename_worker: Optional rename worker for background gallery naming.
    global_byte_counter: Persistent counter tracking ALL galleries.
    gallery_byte_counter: Per-gallery counter (reset after each gallery).
    worker_thread: Optional worker thread reference for bandwidth emission.

Example:
    >>> uploader = IMXUploader(session_id="...")
    >>> engine = UploadEngine(uploader)
    >>> result = engine.run(
    ...     folder_path="/path/to/images",
    ...     gallery_name="My Gallery",
    ...     thumbnail_size=350,
    ...     thumbnail_format=0,
    ...     max_retries=3,
    ...     parallel_batch_size=4,
    ...     template_name="default"
    ... )
    >>> print(f"Uploaded {result['successful_count']} images")
"""
```

### 11. UploadEngine.__init__ (Lines 92-100)

**Current:**
```python
"""Initialize upload engine with counters.

Args:
    uploader: Uploader instance
    rename_worker: Optional rename worker
    global_byte_counter: Persistent counter tracking ALL galleries
    gallery_byte_counter: Per-gallery counter (reset after each gallery)
    worker_thread: Optional worker thread reference for bandwidth emission
"""
```

**Enhanced (to replace):**
```python
"""Initialize upload engine with counters.

Args:
    uploader: Uploader instance implementing required methods.
    rename_worker: Optional rename worker for background naming.
    global_byte_counter: Persistent counter tracking ALL galleries.
    gallery_byte_counter: Per-gallery counter (reset after each gallery).
    worker_thread: Optional worker thread reference for bandwidth emission.
"""
```

### 12. UploadEngine._is_gallery_unnamed (Line 108)

**Current:**
```python
"""Check if gallery is in the unnamed galleries list."""
```

**Enhanced (to replace):**
```python
"""Check if gallery is in the unnamed galleries list.

Args:
    gallery_id: IMX.to gallery ID to check.

Returns:
    True if gallery is pending rename.
"""
```

### 13. UploadEngine.run (Line 117) - MISSING DOCSTRING

**Add comprehensive docstring:**
```python
"""Upload a folder of images to IMX.to as a gallery.

This method orchestrates the entire upload workflow:
1. Scans folder for images (JPEG, PNG, GIF) with natural sorting
2. Filters out already-uploaded files for resume support
3. Creates gallery by uploading first image OR uses existing gallery_id
4. Uploads remaining images concurrently with configurable batch size
5. Retries failed uploads up to max_retries attempts
6. Collects statistics and enriches image metadata
7. Returns comprehensive results dictionary

Image Sorting:
    - Windows Explorer natural sort (StrCmpLogicalW on Windows)
    - Fallback to alphanumeric sort on other platforms
    - Case-insensitive comparison

Gallery Creation Strategy:
    - New galleries: Upload first image with create_gallery=True
    - Faster than web login (avoids browser automation)
    - Clears API cookies to prevent gallery_id reuse
    - Existing galleries: Skip creation, append to existing_gallery_id

Concurrency:
    - ThreadPoolExecutor with parallel_batch_size workers
    - Thread-local HTTP sessions prevent connection overhead
    - Prime pool before entering main loop
    - Graceful shutdown on soft_stop signal

Progress Tracking:
    - on_progress callback invoked after each image
    - ByteCountingCallback updates global counter during transmission
    - Percent completion calculated: (completed / total) * 100

Retry Strategy:
    - Failed images collected during first pass
    - Retry loop runs up to max_retries times
    - Each retry starts with fresh connection
    - Failures after all retries added to failed_details

Resume Support:
    - already_uploaded: Set of filenames to skip
    - existing_gallery_id: Gallery to append to
    - initial_completed: Counts pre-uploaded files in progress

Dimension Handling:
    - precalculated_dimensions: Used if provided (from scan phase)
    - No recalculation during upload (performance optimization)
    - Deferred to scan phase for GUI mode

Statistics Collection:
    - Total upload time (seconds)
    - Uploaded size (bytes)
    - Transfer speed (bytes/sec)
    - Image dimensions (avg, max, min)
    - Success/failure counts

Args:
    folder_path: Absolute path to folder containing images.
    gallery_name: Gallery name (uses folder basename if None).
    thumbnail_size: Thumbnail size in pixels (e.g., 350).
    thumbnail_format: Thumbnail format (0=auto, 1=JPG, 2=PNG).
    max_retries: Maximum retry attempts for failed uploads.
    parallel_batch_size: Number of concurrent upload workers.
    template_name: Template name for gallery formatting.
    already_uploaded: Set of filenames already uploaded (for resume).
    existing_gallery_id: Existing gallery ID to append to.
    precalculated_dimensions: Pre-calculated image dimensions dict.
    on_progress: Callback for progress updates (completed, total, percent, filename).
    should_soft_stop: Callback returning True to gracefully stop upload.
    on_image_uploaded: Callback after each successful image (filename, data, size).

Returns:
    Dictionary containing:
        gallery_url: Full URL to gallery (https://imx.to/g/{id})
        gallery_id: Gallery ID string
        gallery_name: Final gallery name
        images: List of image data dicts with URLs and metadata
        upload_time: Total upload duration (seconds)
        total_size: Total folder size (bytes)
        uploaded_size: Uploaded data size (bytes)
        transfer_speed: Average transfer speed (bytes/sec)
        avg_width, avg_height: Average image dimensions
        max_width, max_height: Maximum image dimensions
        min_width, min_height: Minimum image dimensions
        successful_count: Number of successfully uploaded images
        failed_count: Number of failed images
        failed_details: List of (filename, error_message) tuples
        thumbnail_size, thumbnail_format: Echo of settings
        parallel_batch_size: Echo of batch size
        template_name: Echo of template name
        total_images: Total image count (including already_uploaded)
        started_at: Upload start timestamp (formatted)

Raises:
    FileNotFoundError: If folder_path does not exist.
    ValueError: If no images found in folder.
    Exception: If first image upload fails (prevents gallery creation).

Example:
    >>> engine = UploadEngine(uploader)
    >>> result = engine.run(
    ...     folder_path="/home/user/photos",
    ...     gallery_name="Vacation 2024",
    ...     thumbnail_size=350,
    ...     thumbnail_format=0,
    ...     max_retries=3,
    ...     parallel_batch_size=4,
    ...     template_name="default",
    ...     on_progress=lambda c, t, p, f: print(f"{p}%: {f}")
    ... )
    >>> print(f"Gallery URL: {result['gallery_url']}")
    >>> print(f"Uploaded: {result['successful_count']}/{result['total_images']}")
"""
```

### 14. Helper Functions within run()

#### _natural_sort_key (around line 142)

**Add:**
```python
"""Generate sort key for natural alphanumeric ordering.

Splits filename into text and numeric parts, converting digits to integers
for proper numeric comparison (e.g., "file2" < "file10").

Args:
    name: Filename to generate key for.

Returns:
    Tuple of mixed str/int parts for natural sorting.
"""
```

#### _explorer_sort (around line 155)

**Current:**
```python
"""Windows Explorer (StrCmpLogicalW) ordering; fallback to natural sort on non-Windows."""
```

**Enhanced (to replace):**
```python
"""Sort filenames using Windows Explorer ordering.

Uses StrCmpLogicalW on Windows for native Explorer sort order.
Falls back to natural sort on other platforms.

Args:
    names: List of filenames to sort.

Returns:
    Sorted list of filenames.
"""
```

#### get_thread_session (around line 300)

**Current:**
```python
"""Get or create a session for the current thread"""
```

**Enhanced (to replace):**
```python
"""Get or create a requests session for the current thread.

Thread-local sessions enable connection reuse per worker thread
while avoiding lock contention from shared session objects.

Returns:
    requests.Session configured for this thread.
"""
```

#### upload_single_image (around line 316)

**Add:**
```python
"""Upload a single image to the gallery (worker function).

This function runs in a ThreadPoolExecutor worker. It handles
the upload and error handling for one image.

Args:
    image_file: Filename (not full path) of image to upload.

Returns:
    Tuple of (image_file, image_data_dict, error_message, upload_duration, image_path).
    On success: (filename, {...}, None, 1.234, path)
    On failure: (filename, None, "error message", None, path)
"""
```

#### maybe_soft_stopping (around line 344)

**Add:**
```python
"""Check if upload should stop gracefully.

Returns:
    True if should_soft_stop callback returns True.
"""
```

## Status

- [ ] Module docstring enhanced
- [ ] AtomicCounter class docstring enhanced
- [ ] AtomicCounter methods enhanced
- [ ] ByteCountingCallback class docstring enhanced
- [ ] ByteCountingCallback methods enhanced
- [ ] Type aliases enhanced with inline comments
- [ ] UploadEngine class docstring enhanced
- [ ] UploadEngine.__init__ enhanced
- [ ] UploadEngine._is_gallery_unnamed enhanced
- [ ] UploadEngine.run comprehensive docstring ADDED
- [ ] Helper function docstrings enhanced

## Notes

All changes are purely documentation - no functional code changes.
These docstrings provide comprehensive API documentation for developers
and improve IDE autocomplete/hover information.
