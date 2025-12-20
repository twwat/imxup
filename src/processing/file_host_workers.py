"""
File host upload worker threads.

Background workers that process file host upload queue, create ZIPs,
upload to hosts, and emit progress signals to the GUI.
"""

import time
import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any

from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, QSettings, Qt

from imxup import get_credential, decrypt_password
from src.core.engine import AtomicCounter
from src.core.file_host_config import get_config_manager, HostConfig, get_file_host_setting
from src.network.file_host_client import FileHostClient
from src.processing.file_host_coordinator import get_coordinator
from src.storage.database import QueueStore
from src.utils.logger import log
from src.utils.zip_manager import get_zip_manager
from src.utils.format_utils import format_binary_size


class FileHostWorker(QThread):
    """Worker thread for file host uploads.

    One worker per enabled host - handles uploads, tests, and storage checks.
    """

    # Signals for communication with GUI
    upload_started = pyqtSignal(int, str)  # db_id, host_name
    upload_progress = pyqtSignal(int, str, int, int, float)  # db_id, host_name, uploaded_bytes, total_bytes, speed_bps
    upload_completed = pyqtSignal(int, str, dict)  # db_id, host_name, result_dict
    upload_failed = pyqtSignal(int, str, str)  # db_id, host_name, error_message
    bandwidth_updated = pyqtSignal(float)  # Instantaneous KB/s from pycurl
    log_message = pyqtSignal([str], [str, str])  # Overloaded: (message) or (level, message) for backward compatibility

    # New signals for testing and storage
    storage_updated = pyqtSignal(str, object, object)  # host_id, total_bytes, left_bytes (use object for large ints)
    test_completed = pyqtSignal(str, dict)  # host_id, results_dict
    spinup_complete = pyqtSignal(str, str)  # host_id, error_message (empty = success)
    credentials_update_requested = pyqtSignal(str)  # credentials (for updating credentials from dialog)
    status_updated = pyqtSignal(str, str)  # host_id, status_text

    def __init__(self, host_id: str, queue_store: QueueStore):
        """Initialize file host worker for a specific host.

        Args:
            host_id: Unique host identifier (e.g., 'rapidgator')
            queue_store: Database queue store
        """
        super().__init__()

        self.host_id = host_id
        self.queue_store = queue_store
        self.config_manager = get_config_manager()
        self.coordinator = get_coordinator()
        self.zip_manager = get_zip_manager()
        self.settings = QSettings("ImxUploader", "ImxUploadGUI")

        # Get display name for logs (e.g., "RapidGator" instead of "rapidgator")
        host_config = self.config_manager.get_host(host_id)
        self.log_prefix = f"{host_config.name} Worker" if host_config else f"{host_id} Worker"

        self.running = True
        self.paused = False

        # Bandwidth tracking
        self.bandwidth_counter = AtomicCounter()
        self._bw_last_bytes = 0
        self._bw_last_time = time.time()
        self._bw_last_emit = 0.0

        # Load host credentials from settings
        self.host_credentials: Dict[str, str] = {}
        self._load_credentials()

        # Persistent session state (shared across all client instances)
        self._session_cookies: Dict[str, str] = {}  # Persists across operations
        self._session_token: Optional[str] = None    # For session_id_regex hosts
        self._session_timestamp: Optional[float] = None
        self._session_lock = threading.Lock()        # Thread safety for session access

        # Test request queue (processed in run() loop to execute in worker thread)
        self._test_queue: list[str] = []  # List of credentials to test
        self._test_queue_lock = threading.Lock()

        # Current upload tracking
        self.current_upload_id: Optional[int] = None
        self.current_host: Optional[str] = None
        self.current_db_id: Optional[int] = None
        self._should_stop_current = False

        # Thread-safe upload throttle state
        self._upload_throttle_state = {}  # {(db_id, host): {'last_emit': time, 'last_progress': (up, total)}}
        self._throttle_lock = threading.Lock()

        # Connect credentials update signal
        self.credentials_update_requested.connect(self._update_credentials)

    def _log(self, message: str, level: str = "info") -> None:
        """Helper to log with host name prefix.

        Args:
            message: Log message
            level: Log level (info, debug, warning, error)
        """
        # Emit signal for any connected dialogs (specify two-argument overload)
        self.log_message[str, str].emit(level, message)

        # Write to file logger
        log(f"{self.log_prefix}: {message}", level=level, category="file_hosts")

    def _load_credentials(self) -> None:
        """Load this host's credentials from QSettings."""
        encrypted_creds = get_credential(f'file_host_{self.host_id}_credentials')
        if encrypted_creds:
            try:
                credentials = decrypt_password(encrypted_creds)
                if credentials:
                    self.host_credentials[self.host_id] = credentials
                    self._log("Loaded credentials")
            except Exception as e:
                self._log(f"Failed to decrypt credentials: {e}")

    @pyqtSlot(str)
    def _update_credentials(self, credentials: str) -> None:
        """Update credentials for this host (called via signal from dialog).

        Args:
            credentials: New credentials string (username:password or api_key)
        """
        if credentials:
            self.host_credentials[self.host_id] = credentials
            self._log("Credentials updated from dialog", level="debug")
        else:
            # Empty credentials = remove
            self.host_credentials.pop(self.host_id, None)
            self._log("Credentials cleared", level="debug")

    def _cleanup_upload_throttle_state(self, db_id: int, host_name: str):
        """Clean up throttling state for an upload to prevent memory leaks."""
        with self._throttle_lock:
            self._upload_throttle_state.pop((db_id, host_name), None)

    def _create_client(self, host_config: HostConfig) -> FileHostClient:
        """Create FileHostClient with session reuse.

        Thread-safe: Reads session state under lock, injects into new client.

        Args:
            host_config: Host configuration

        Returns:
            Configured FileHostClient instance with session reuse
        """
        credentials = self.host_credentials.get(self.host_id)

        # Thread-safe read of session state
        with self._session_lock:
            session_cookies = self._session_cookies.copy() if self._session_cookies else None
            session_token = self._session_token
            session_timestamp = self._session_timestamp

        # Create client with session injection (no login if session exists)
        client = FileHostClient(
            host_config=host_config,
            bandwidth_counter=self.bandwidth_counter,
            credentials=credentials,
            host_id=self.host_id,
            log_callback=self._log,
            # NEW: Inject session (reuse if exists, fresh login if None)
            session_cookies=session_cookies,
            session_token=session_token,
            session_timestamp=session_timestamp
        )

        return client

    def _update_session_from_client(self, client: FileHostClient) -> None:
        """Extract and persist session state from client.

        Thread-safe: Writes session state under lock.

        Args:
            client: FileHostClient instance to extract session from
        """
        session_state = client.get_session_state()

        with self._session_lock:
            self._session_cookies = session_state['cookies']
            self._session_token = session_state['token']
            self._session_timestamp = session_state['timestamp']

        if session_state['timestamp']:
            age = time.time() - session_state['timestamp']
            self._log(f"Session state persisted (age: {age:.0f}s, cookies: {len(session_state['cookies'])})", level="debug")

    def queue_test_request(self, credentials: str) -> None:
        """Queue a test request to be processed in the worker thread.

        This method is called from the GUI thread and queues the request
        for processing in the worker's run() loop where it executes in
        the worker thread context (non-blocking).

        Args:
            credentials: Credentials to test with
        """
        with self._test_queue_lock:
            self._test_queue.append(credentials)
            self._log("Test request queued", level="debug")

    def stop(self) -> None:
        """Stop the worker thread."""
        self._log("Stopping file host worker...", level="debug")
        self.running = False
        self.wait()

    def pause(self) -> None:
        """Pause processing new uploads."""
        self.paused = True
        self._log("File host worker paused", level="info")

    def resume(self) -> None:
        """Resume processing uploads."""
        self.paused = False
        self._log("File host worker resumed", level="info")

    def _is_retryable_error(self, error: Exception, error_msg: str) -> bool:
        """
        Determine if an error should trigger a retry attempt.

        Non-retryable errors are permanent failures that won't be fixed by retrying:
        - Folder/file not found
        - Permission denied (folder-level)
        - Invalid path format
        - Not a directory

        Retryable errors are transient network/server issues:
        - Connection errors
        - Timeouts
        - HTTP 5xx errors
        - Rate limits

        Args:
            error: The exception that occurred
            error_msg: Error message string

        Returns:
            bool: True if error should trigger retry, False if should fail immediately
        """
        # Non-retryable error types (permanent failures)
        NON_RETRYABLE_ERRORS = (
            FileNotFoundError,
            NotADirectoryError,
            ValueError,  # Invalid path format
        )

        if isinstance(error, NON_RETRYABLE_ERRORS):
            self._log(f"Error is non-retryable (type: {type(error).__name__}), failing immediately", level="debug")
            return False

        # Check error message for folder/path-related issues
        error_lower = error_msg.lower()
        non_retryable_keywords = [
            'folder not found',
            'does not exist',
            'not a directory',
            'not a folder',
            'invalid path',
            'path does not exist',
            'no such file or directory'
        ]

        if any(keyword in error_lower for keyword in non_retryable_keywords):
            self._log(f"Error message indicates non-retryable issue: {error_msg}", level="debug")
            return False

        # Permission errors - only folder-level permission errors are non-retryable
        # Server-level permission errors (upload denied) may be retryable after re-auth
        if isinstance(error, PermissionError):
            if 'folder' in error_lower or 'directory' in error_lower:
                self._log("Folder permission error is non-retryable", level="debug")
                return False
            # Server permission errors may be retryable
            self._log("Server permission error, allowing retry", level="debug")
            return True

        # All other errors (network, timeout, server errors) are retryable
        self._log(f"Error is retryable (type: {type(error).__name__})", level="debug")
        return True

    def cancel_current_upload(self) -> None:
        """Cancel the current upload."""
        self._should_stop_current = True
        self._log(
            f"Cancel requested for current upload: {self.current_host} (gallery {self.current_db_id})",
            level="info"
        )

    def run(self):
        """Main worker thread loop - process uploads for this host only."""
        self._log("Worker started", level="info")
        self.status_updated.emit(self.host_id, "starting")
        log(f"DEBUG: Emitted status signal: {self.host_id} -> starting", level="debug", category="file_hosts")

        # Test credentials during spinup (power button paradigm)
        host_config = self.config_manager.get_host(self.host_id)
        if host_config and host_config.requires_auth:
            credentials = self.host_credentials.get(self.host_id)
            if not credentials:
                error = "Credentials required but not configured"
                self._log(error, level="warning")
                self.spinup_complete.emit(self.host_id, error)
                self.running = False
                return

            self._log("Testing credentials during spinup...", level="debug")
            self.status_updated.emit(self.host_id, "authenticating")
            log(f"DEBUG: Emitted status signal: {self.host_id} -> authenticating", level="debug", category="file_hosts")

            spinup_success = False
            spinup_error = ""

            try:
                client = self._create_client(host_config)
                cred_result = client.test_credentials()
                if not cred_result.get('success'):
                    spinup_error = cred_result.get('message', 'Credential validation failed')
                    self._log(f"Credential test failed: {spinup_error}", level="warning")
                else:
                    # Save storage if available
                    user_info = cred_result.get('user_info', {})
                    if user_info:
                        storage_total = user_info.get('storage_total')
                        storage_left = user_info.get('storage_left')
                        if storage_total is not None and storage_left is not None:
                            try:
                                total = int(storage_total)
                                left = int(storage_left)
                                self._save_storage_cache(total, left)
                                self.storage_updated.emit(self.host_id, total, left)
                                #self._log(f"Cached storage during spinup: {format_binary_size(left)}/{format_binary_size(total)}", level="debug")
                            except (ValueError, TypeError) as e:
                                self._log(f"Failed to parse storage: {e}", level="debug")

                    self._log("Successfully validated credentials; spinup complete!", level="info")
                    spinup_success = True
                    self.status_updated.emit(self.host_id, "idle")
                    log(f"Emitted status signal: {self.host_id} -> idle", level="debug", category="file_hosts")

                    # Persist session from first login
                    self._update_session_from_client(client)

            except Exception as e:
                import traceback
                spinup_error = f"Credential test exception: {str(e)}"
                self._log(f"{spinup_error}\n{traceback.format_exc()}", level="error")

            finally:
                # ALWAYS emit spinup_complete signal - manager depends on this for cleanup
                # Emit success (empty error) or failure (with error message)
                self.spinup_complete.emit(self.host_id, "" if spinup_success else spinup_error)

            # If spinup failed, stop worker thread
            if not spinup_success:
                self.running = False
                return
        else:
            # No auth required - immediately signal idle
            self.status_updated.emit(self.host_id, "idle")
            log(f"Emitted status signal: {self.host_id} -> idle", level="debug", category="file_hosts")
            self.spinup_complete.emit(self.host_id, "")

        while self.running:
            try:
                if self.paused:
                    time.sleep(0.5)
                    continue

                # Check for test requests (process in worker thread)
                test_credentials = None
                with self._test_queue_lock:
                    if self._test_queue:
                        test_credentials = self._test_queue.pop(0)

                if test_credentials:
                    # Update credentials and run test in worker thread
                    self.host_credentials[self.host_id] = test_credentials
                    self._log("Processing test request in worker thread", level="debug")
                    self.test_connection()
                    # Continue loop to check for more tests or uploads
                    continue

                # Get next pending upload for THIS host only
                pending_uploads = self.queue_store.get_pending_file_host_uploads(host_name=self.host_id)

                if not pending_uploads:
                    # No work to do, emit bandwidth and wait
                    self._emit_bandwidth()
                    time.sleep(1.0)
                    continue

                # Process next upload
                upload = pending_uploads[0]
                host_name = upload['host_name']
                db_id = upload['gallery_fk']
                upload_id = upload['id']
                gallery_path = upload['gallery_path']

                # Convert WSL2 paths and validate folder exists BEFORE marking as uploading
                from src.utils.system_utils import convert_to_wsl_path
                folder_path = convert_to_wsl_path(gallery_path)

                if not folder_path.exists():
                    error_msg = f"Gallery folder not found: {gallery_path}"
                    if str(gallery_path) != str(folder_path):
                        error_msg += f" (tried WSL2 path: {folder_path})"

                    self._log(f"FAIL FAST: {error_msg}", level="error")
                    # CRITICAL: Emit signal FIRST before DB write (fail-fast path)
                    self.upload_failed.emit(db_id, host_name, error_msg)
                    self.queue_store.update_file_host_upload(
                        upload_id,
                        status='failed',
                        finished_ts=int(time.time()),
                        error_message=error_msg
                    )
                    continue

                if not folder_path.is_dir():
                    error_msg = f"Path is not a directory: {gallery_path}"
                    self._log(f"FAIL FAST: {error_msg}", level="error")
                    # CRITICAL: Emit signal FIRST before DB write (fail-fast path)
                    self.upload_failed.emit(db_id, host_name, error_msg)
                    self.queue_store.update_file_host_upload(
                        upload_id,
                        status='failed',
                        finished_ts=int(time.time()),
                        error_message=error_msg
                    )
                    continue

                # Check if host is enabled (should always be true since worker exists)
                host_config = self.config_manager.get_host(host_name)
                host_enabled = get_file_host_setting(host_name, "enabled", "bool")
                if not host_config or not host_enabled:
                    self._log(
                        f"Host {host_name} is disabled, skipping upload for gallery {db_id}",
                        level="warning")
                    self.queue_store.update_file_host_upload(
                        upload_id,
                        status='failed',
                        error_message=f"Host {host_name} is disabled"
                    )
                    continue

                # Check if we can start upload (connection limits)
                if not self.coordinator.can_start_upload(host_name):
                    self._log(
                        f"Connection limit reached for {host_name}, waiting...",
                        level="debug")
                    time.sleep(1.0)
                    continue

                # Acquire upload slot and process
                try:
                    with self.coordinator.acquire_slot(db_id, host_name, timeout=5.0):
                        self._process_upload(
                            upload_id=upload_id,
                            db_id=db_id,
                            gallery_path=gallery_path,
                            gallery_name=upload['gallery_name'],
                            host_name=host_name,
                            host_config=host_config
                        )
                except TimeoutError:
                    self._log(
                        f"Could not acquire upload slot for {host_name}, retrying...",
                        level="debug")
                    time.sleep(1.0)

            except Exception as e:
                self._log(f"Error in file host worker loop: {e}", level="error")
                import traceback
                traceback.print_exc()
                time.sleep(1.0)

        self._log("Worker stopped", level="info")

    def _process_upload(
        self,
        upload_id: int,
        db_id: int,
        gallery_path: str,
        gallery_name: Optional[str],
        host_name: str,
        host_config: HostConfig
    ):
        """Process a single file host upload.

        Args:
            upload_id: Database upload record ID
            db_id: Database ID for the upload
            gallery_path: Path to gallery folder
            gallery_name: Gallery name
            host_name: Host name
            host_config: Host configuration
        """
        self.current_upload_id = upload_id
        self.current_host = host_name
        self.current_db_id = db_id
        self._should_stop_current = False

        # Initialize timing and size tracking for metrics
        upload_start_time = time.time()
        zip_size = 0

        self._log(
            f"Starting upload to {host_name} for gallery {db_id} ({gallery_name})",
            level="info"
        )

        # CRITICAL: Emit started signal FIRST before database write
        # This ensures GUI gets immediate notification without waiting for DB
        self.upload_started.emit(db_id, host_name)

        # Update status to uploading (AFTER signal emission)
        self.queue_store.update_file_host_upload(
            upload_id,
            status='uploading',
            started_ts=int(time.time())
        )

        try:
            # Step 1: Create or reuse ZIP (with WSL2 path conversion)
            from src.utils.system_utils import convert_to_wsl_path
            folder_path = convert_to_wsl_path(gallery_path)

            if not folder_path.exists():
                error_msg = f"Gallery folder not found: {gallery_path}"
                if str(gallery_path) != str(folder_path):
                    error_msg += f" (WSL2 path: {folder_path})"
                raise FileNotFoundError(error_msg)

            zip_path = self.zip_manager.create_or_reuse_zip(
                db_id=db_id,
                folder_path=folder_path,
                gallery_name=gallery_name
            )

            zip_size = zip_path.stat().st_size

            # Update ZIP path and total bytes
            self.queue_store.update_file_host_upload(
                upload_id,
                zip_path=str(zip_path),
                total_bytes=zip_size
            )

            # Step 2: Create client and upload (reuses session if available)
            client = self._create_client(host_config)

            def on_progress(uploaded: int, total: int, speed_bps: float = 0.0):
                """Progress callback from pycurl with speed tracking."""
                try:
                    # Throttle progress signal emissions to max 4 per second using instance-level state
                    current_time = time.time()
                    upload_key = (db_id, host_name)

                    should_emit = False
                    with self._throttle_lock:
                        state = self._upload_throttle_state.setdefault(upload_key, {
                            'last_emit': 0,
                            'last_progress': (0, 0)
                        })

                        time_elapsed = current_time - state['last_emit']
                        if time_elapsed >= 0.25:  # Max 4 per second
                            last_progress = state['last_progress']
                            # Emit if progress changed or it's been >0.5s (prevent frozen UI)
                            if (uploaded, total) != last_progress or time_elapsed >= 0.5:
                                should_emit = True
                                state['last_emit'] = current_time
                                state['last_progress'] = (uploaded, total)

                    # Emit outside the lock to avoid deadlocks
                    if should_emit:
                        self.upload_progress.emit(db_id, host_name, uploaded, total, speed_bps)

                    # Emit bandwidth periodically (speed_bps is bytes/sec, convert to KB/s)
                    if speed_bps > 0:
                        kbps = speed_bps / 1024.0
                        self._emit_bandwidth_immediate(kbps)
                    else:
                        self._emit_bandwidth()
                except Exception as e:
                    import traceback
                    self._log(f"Progress callback error: {e}\n{traceback.format_exc()}", level="error")
                    self._cleanup_upload_throttle_state(db_id, host_name)
                    # Continue upload - don't abort on display errors

            def should_stop():
                """Check if upload should be cancelled."""
                return self._should_stop_current or not self.running

            # Reset upload timing just before actual transfer (after ZIP creation)
            upload_start_time = time.time()

            # Perform upload
            result = client.upload_file(
                file_path=zip_path,
                on_progress=on_progress,
                should_stop=should_stop
            )

            # Calculate transfer time for metrics
            upload_elapsed_time = time.time() - upload_start_time

            # Step 4: Handle result
            if result.get('status') == 'success':
                download_url = result.get('url', '')
                file_id = result.get('upload_id') or result.get('file_id', '')

                # CRITICAL: Emit signal FIRST before any blocking operations
                # This ensures GUI gets immediate notification without waiting for DB writes
                self.upload_completed.emit(db_id, host_name, result)

                self._cleanup_upload_throttle_state(db_id, host_name)

                # Update database with success (AFTER signal emission)
                self.queue_store.update_file_host_upload(
                    upload_id,
                    status='completed',
                    finished_ts=int(time.time()),
                    download_url=download_url,
                    file_id=file_id,
                    file_name=zip_path.name,
                    raw_response=str(result.get('raw_response', {}))[:10000],  # Limit size
                    uploaded_bytes=zip_size
                )

                # Record success (fast operation, no blocking)
                self.coordinator.record_completion(success=True)

                # Record metrics for successful transfer (async via queue)
                from src.utils.metrics_store import get_metrics_store
                metrics_store = get_metrics_store()
                if metrics_store:
                    metrics_store.record_transfer(
                        host_name=self.host_id,
                        bytes_uploaded=zip_size,
                        transfer_time=upload_elapsed_time,
                        success=True
                    )
                self._log(
                    f"Successfully uploaded {gallery_name}: {download_url}",
                    level="info")
                
                # Log raw server response for debugging (with linebreaks as \n text)
                raw_resp = result.get('raw_response', {})
                if raw_resp:
                    resp_str = json.dumps(raw_resp, ensure_ascii=False).replace('\n', '\\n')
                    self._log(f"Server response: {resp_str}", level="debug")
                    
                # Update session after successful upload (in case tokens refreshed)
                self._update_session_from_client(client)
                
            else:
                raise Exception(result.get('error', 'Upload failed'))

        except Exception as e:
            error_msg = str(e)
            self._log(
                f"Upload failed for gallery {db_id}: {error_msg}",
                level="error")

            # Get current retry count
            uploads = self.queue_store.get_file_host_uploads(gallery_path)
            current_upload = next((u for u in uploads if u['id'] == upload_id), None)
            retry_count = current_upload['retry_count'] if current_upload else 0

            # Check if we should retry
            auto_retry = get_file_host_setting(host_name, "auto_retry", "bool")
            max_retries = get_file_host_setting(host_name, "max_retries", "int")

            # Check if error is retryable (don't retry folder/permission errors)
            is_retryable = self._is_retryable_error(e, error_msg)

            should_retry = (
                auto_retry and
                retry_count < max_retries and
                not self._should_stop_current and
                is_retryable  # Only retry if error is recoverable
            )

            if should_retry:
                self._cleanup_upload_throttle_state(db_id, host_name)  # ADD THIS LINE
                # Increment retry count and set back to pending
                self.queue_store.update_file_host_upload(
                    upload_id,
                    status='pending',
                    error_message=error_msg,
                    retry_count=retry_count + 1
                )

                self._log(
                    f"Retrying upload '{gallery_name}' (attempt {retry_count + 1}/{max_retries})",
                    level="info"
                )
            else:
                # CRITICAL: Emit failed signal FIRST before blocking operations
                # This ensures GUI gets immediate notification
                self.upload_failed.emit(db_id, host_name, error_msg)

                self._cleanup_upload_throttle_state(db_id, host_name)

                # Mark as failed (AFTER signal emission)
                self.queue_store.update_file_host_upload(
                    upload_id,
                    status='failed',
                    finished_ts=int(time.time()),
                    error_message=error_msg
                )

                # Record failure (fast operation)
                self.coordinator.record_completion(success=False)

                # Record metrics for failed transfer (async via queue)
                from src.utils.metrics_store import get_metrics_store
                metrics_store = get_metrics_store()
                if metrics_store:
                    # Calculate elapsed time from upload start
                    elapsed = time.time() - upload_start_time
                    metrics_store.record_transfer(
                        host_name=self.host_id,
                        bytes_uploaded=0,  # Failed uploads don't count bytes
                        transfer_time=elapsed,
                        success=False
                    )

        finally:
            # Release ZIP reference
            self.zip_manager.release_zip(db_id)

            # Clear current upload tracking
            self.current_upload_id = None
            self.current_host = None
            self.current_db_id = None
            self._should_stop_current = False

    def _emit_bandwidth(self):
        """Calculate and emit current bandwidth."""
        now = time.time()

        # Only emit every 0.5 seconds
        if now - self._bw_last_emit < 0.5:
            return

        elapsed = now - self._bw_last_time
        if elapsed > 0:
            current_bytes = self.bandwidth_counter.get()
            bytes_transferred = current_bytes - self._bw_last_bytes

            # Calculate KB/s
            kbps = (bytes_transferred / 1024.0) / elapsed

            # Emit signal
            self.bandwidth_updated.emit(kbps)

            # Update tracking
            self._bw_last_bytes = current_bytes
            self._bw_last_time = now
            self._bw_last_emit = now

    def _emit_bandwidth_immediate(self, kbps: float):
        """Emit bandwidth immediately without throttling (for pycurl-calculated speeds)."""
        now = time.time()

        # Still throttle to 0.5 seconds to avoid GUI overload
        if now - self._bw_last_emit < 0.5:
            return

        # Emit the speed directly (already calculated by pycurl callback)
        self.bandwidth_updated.emit(kbps)

        # Update tracking
        self._bw_last_emit = now

    def get_current_upload_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current upload.

        Returns:
            Dictionary with current upload info, or None
        """
        if self.current_upload_id is None:
            return None

        return {
            'upload_id': self.current_upload_id,
            'db_id': self.current_db_id,
            'host_name': self.current_host
        }

    # =========================================================================
    # Storage and Testing Methods (bypass coordinator, for UI operations)
    # =========================================================================

    def check_storage(self) -> None:
        """Check storage from cache (30min TTL) or fetch from server.

        Emits storage_updated signal with results.
        Uses QSettings cache to avoid unnecessary API calls.
        """
        # Step 0: Check if host even supports storage info
        host_config = self.config_manager.get_host(self.host_id)
        if not host_config or not host_config.user_info_url:
            # Host doesn't have storage tracking - skip silently
            return

        # Step 1: Check cache first
        cache = self._load_storage_cache()
        if cache:
            age = int(time.time()) - cache['timestamp']
            if age < 1800:  # 30 minutes TTL
                # Cache valid - emit immediately
                self._log(
                    f"Using cached storage (age: {age}s)",
                    level="debug"
                )
                self.storage_updated.emit(self.host_id, cache['total'], cache['left'])
                return

        # Step 2: Cache invalid/missing - fetch from server
        self._log(
            f"Fetching storage from server",
            level="debug"
        )

        try:
            host_config = self.config_manager.get_host(self.host_id)
            if not host_config:
                raise Exception(f"Host config not found: {self.host_id}")

            # Create client (reuses session if available)
            client = self._create_client(host_config)

            # Check if storage was cached during login (saves an API call!)
            cached_storage = client.get_cached_storage_from_login()
            if cached_storage and cached_storage.get('storage_total') and cached_storage.get('storage_left'):
                self._log(f"Cached storage from login: {json.dumps(cached_storage, indent=2).replace(chr(10), '\n')}", level="debug")

                total = int(cached_storage.get('storage_total') or 0)
                left = int(cached_storage.get('storage_left') or 0)
                self._log(
                    f"Got storage from login response for {self.host_id} (no /info call needed!)",
                    level="debug"
                )
            else:
                # No storage in login - make separate /info call
                user_info = client.get_user_info()

                user_info_formatted = json.dumps(user_info, indent=2).replace(chr(10), '\n') if user_info else "None"
                self._log(f"Fetched from /info call: {user_info_formatted}", level="debug")

                total_raw = user_info.get('storage_total')
                left_raw = user_info.get('storage_left')

                self._log(
                    f"Extracted storage_total={total_raw}, storage_left={left_raw}",
                    level="debug"
                )

                # Validate before emitting - DO NOT overwrite good data with bad data
                if total_raw is None or left_raw is None or total_raw <= 0 or left_raw < 0:
                    self._log(
                        f"Invalid storage data from API (total={total_raw}, left={left_raw}) - keeping cached data",
                        level="debug"
                    )
                    return  # Do NOT emit signal, do NOT save to cache

                # Convert to int only after validation
                total = int(total_raw)
                left = int(left_raw)

            # Step 3: Save to cache (only if we have valid data)
            self._save_storage_cache(total, left)

            # Step 4: Emit signal (only if we have valid data)
            self.storage_updated.emit(self.host_id, total, left)

            self._log(
                f"Storage updated: {left}/{total} bytes free",
                level="info")

            # Update session after storage check (in case tokens refreshed)
            self._update_session_from_client(client)

        except Exception as e:
            self._log(
                f"Storage check failed: {e}",
                level="debug")
            # Do NOT emit signal with bad data

    @pyqtSlot()
    def test_connection(self) -> None:
        """Run full test suite: credentials → user_info → upload → delete.

        Emits test_completed signal with results dict.
        Bypasses coordinator - this is a UI test operation.
        """
        self._log(
            "Starting connection test",
            level="info")

        results = {
            'timestamp': int(time.time()),
            'credentials_valid': False,
            'user_info_valid': False,
            'upload_success': False,
            'delete_success': False,
            'error_message': ''
        }

        try:
            host_config = self.config_manager.get_host(self.host_id)
            if not host_config:
                raise Exception(f"Host config not found: {self.host_id}")

            # Create client (reuses session if available)
            client = self._create_client(host_config)

            # Test 1: Credentials
            #self._log("Testing credentials...", level="debug")
            cred_result = client.test_credentials()

            if not cred_result.get('success'):
                results['error_message'] = cred_result.get('message', 'Credential test failed')
                self._save_test_results(results)
                self.test_completed.emit(self.host_id, results)
                self._log("Test #1: FAIL - Unable authenticate using credentials", level="warning")
                return

            results['credentials_valid'] = True
            results['user_info_valid'] = bool(cred_result.get('user_info'))
            self._log("Test #1: PASS - Authenticated successfully using credentials", level="debug")

            # Cache storage info if available (opportunistic caching during test)
            user_info = cred_result.get('user_info', {})
            if not user_info:
                self._log("Test #2: FAIL - Unable to get user info", level="debug")
            else:
                self._log("Test #2: PASS - Successfully fetched user info", level="debug")
            # Format user_info for log viewer (with escaped newlines for expansion)

            user_info_formatted = json.dumps(user_info, indent=2).replace(chr(10), '\\n') if user_info else "None"
            self._log(f"user_info from test: {user_info_formatted}", level="debug")

            if user_info:
                storage_total = user_info.get('storage_total')
                storage_left = user_info.get('storage_left')
                self._log(
                    f"Extracted storage values: storage_total = {storage_total} ({type(storage_total).__name__})  storage_left = {storage_left} ({type(storage_left).__name__})",
                    level="debug"
                )
                if storage_total is not None and storage_left is not None:
                    try:
                        total = int(storage_total or 0)
                        left = int(storage_left or 0)
                        self._save_storage_cache(total, left)
                        self.storage_updated.emit(self.host_id, total, left)
                        self._log(f"Cached storage during test: {left}/{total} bytes", level="debug")
                    except (ValueError, TypeError) as e:
                        self._log(f"Failed to parse storage during test: {e}", level="error")
                else:
                    self._log(
                        f"Storage data missing in test response (total={storage_total}, left={storage_left})",
                        level="debug"
                    )
            else:
                self._log("No user_info in test credentials response", level="debug")

            # Test 2: Upload
            #self._log("(Test 3/4): Testing upload functionality...", level="debug")
            upload_result = client.test_upload(cleanup=False)

            if not upload_result.get('success'):
                results['error_message'] = upload_result.get('message', 'Upload test failed')
                self._save_test_results(results)
                self.test_completed.emit(self.host_id, results)
                self._log("Test #3: FAIL - failed to upload test file", level="warning")
                return

            results['upload_success'] = True
            self._log("Test #3: PASS - uploaded test file successfully", level="info")
            # Test 3: Delete (if host supports it)
            file_id = upload_result.get('file_id') or upload_result.get('upload_id')
            if file_id and host_config.delete_url:
                try:
                    #self._log("(Test 4/4): Testing delete functionality...", level="debug")
                    client.delete_file(file_id)
                    results['delete_success'] = True
                    self._log("Test #4: PASS - deleted test file successfully", level="info")
                except Exception as e:
                    self._log(f"Test #4: FAIL - failed to delete test file: {e}", level="error")
                    # Don't fail entire test if delete fails
                    results['delete_success'] = False

            # All tests passed (or delete not supported)
            self._save_test_results(results)

            # Update session after test completes (in case tokens refreshed)
            self._update_session_from_client(client)

            self.test_completed.emit(self.host_id, results)

            passed_count = sum([
                1 if results['credentials_valid'] else 0,
                1 if results['user_info_valid'] else 0,
                1 if results['upload_success'] else 0,
                1 if results['delete_success'] else 0
            ])
            self._log(
                f"Tests completed: {passed_count}/4 tests passed",
                level="info"
            )

        except Exception as e:
            results['error_message'] = str(e)
            self._save_test_results(results)
            self.test_completed.emit(self.host_id, results)

            self._log(
                f"Connection test failed: {e}",
                level="warning")

    # =========================================================================
    # Cache Helper Methods
    # =========================================================================

    def _load_storage_cache(self) -> Optional[Dict[str, Any]]:
        """Load storage cache from QSettings.

        Returns:
            Cache dict with timestamp, total, left, or None if no cache
        """
        ts = self.settings.value(f"FileHosts/{self.host_id}/storage_ts", None, type=int)
        if not ts or ts == 0:
            return None

        # Use str type and manual conversion to avoid Qt's 32-bit int overflow
        total_str = self.settings.value(f"FileHosts/{self.host_id}/storage_total", "0")
        left_str = self.settings.value(f"FileHosts/{self.host_id}/storage_left", "0")

        return {
            'timestamp': ts,
            'total': int(total_str) if total_str else 0,
            'left': int(left_str) if left_str else 0
        }

    def _save_storage_cache(self, total: int, left: int) -> None:
        """Save storage cache to QSettings.

        Storage values are saved as strings to avoid Qt's 32-bit int overflow
        on some platforms. Always load with manual int() conversion.

        Args:
            total: Total storage in bytes
            left: Free storage in bytes
        """
        self.settings.setValue(f"FileHosts/{self.host_id}/storage_ts", int(time.time()))
        self.settings.setValue(f"FileHosts/{self.host_id}/storage_total", str(total))
        self.settings.setValue(f"FileHosts/{self.host_id}/storage_left", str(left))
        self._log(f"Storage cache updated: {format_binary_size(left)}/{format_binary_size(total)} bytes", level="debug")
        self.settings.sync()

    def _save_test_results(self, results: Dict[str, Any]) -> None:
        """Save test results to QSettings.

        Args:
            results: Test results dictionary
        """
        prefix = f"FileHosts/TestResults/{self.host_id}"
        self.settings.setValue(f"{prefix}/timestamp", results['timestamp'])
        self.settings.setValue(f"{prefix}/credentials_valid", results['credentials_valid'])
        self.settings.setValue(f"{prefix}/user_info_valid", results['user_info_valid'])
        self.settings.setValue(f"{prefix}/upload_success", results['upload_success'])
        self.settings.setValue(f"{prefix}/delete_success", results['delete_success'])
        self.settings.setValue(f"{prefix}/error_message", results['error_message'])
        self.settings.sync()

    def load_test_results(self) -> Optional[Dict[str, Any]]:
        """Load test results from QSettings.

        Returns:
            Test results dict with timestamp and test outcomes, or None if no results
        """
        prefix = f"FileHosts/TestResults/{self.host_id}"
        ts = self.settings.value(f"{prefix}/timestamp", None, type=int)
        if not ts or ts == 0:
            return None

        return {
            'timestamp': ts,
            'credentials_valid': self.settings.value(f"{prefix}/credentials_valid", False, type=bool),
            'user_info_valid': self.settings.value(f"{prefix}/user_info_valid", False, type=bool),
            'upload_success': self.settings.value(f"{prefix}/upload_success", False, type=bool),
            'delete_success': self.settings.value(f"{prefix}/delete_success", False, type=bool),
            'error_message': self.settings.value(f"{prefix}/error_message", '', type=str)
        }
