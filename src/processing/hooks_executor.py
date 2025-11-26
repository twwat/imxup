"""
External program hooks executor for running programs at gallery lifecycle events.
"""

import os
import subprocess
import json
import configparser
import concurrent.futures
import time
import sys
from typing import Any, Dict, List, Optional, Tuple
from imxup import get_config_path
from src.utils.logger import log


class HooksExecutor:
    """Executes external programs at gallery lifecycle events"""

    def __init__(self):
        # Don't cache config - reload fresh each time execute_hooks is called
        pass

    def _remove_temp_file_with_retry(self, file_path: str, max_retries: int = 5, initial_delay: float = 0.1) -> bool:
        """
        Attempt to remove a temporary file with exponential backoff retries.

        On Windows, external processes may hold file handles briefly after subprocess.run() returns.
        This method retries with increasing delays to allow processes to fully release the file.

        Args:
            file_path: Path to file to remove
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds (doubles each retry)

        Returns:
            True if file was removed, False if all retries failed
        """
        if not os.path.exists(file_path):
            return True

        delay = initial_delay
        for attempt in range(max_retries):
            try:
                os.remove(file_path)
                if attempt > 0:
                    log(f"Successfully removed temporary file on attempt {attempt + 1}: {file_path}", level="debug", category="hooks")
                else:
                    log(f"Removed temporary file: {file_path}", level="debug", category="hooks")
                return True
            except PermissionError as e:
                # File is locked by another process
                if attempt < max_retries - 1:
                    log(f"File locked (attempt {attempt + 1}/{max_retries}), waiting {delay:.2f}s: {file_path}", level="debug", category="hooks")
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    # Final attempt failed - log as warning but don't fail the operation
                    log(f"Could not remove temporary file after {max_retries} attempts (file will be cleaned up by OS): {file_path}", level="warning", category="hooks")
                    return False
            except Exception as e:
                # Other errors (file not found, etc.) - just log and move on
                log(f"Error removing temporary file: {e}", level="debug", category="hooks")
                return False

        return False

    def _load_config(self) -> Dict:
        """Load external apps configuration from INI file"""
        config = configparser.ConfigParser()
        config_file = get_config_path()

        if os.path.exists(config_file):
            config.read(config_file)

        hooks_config = {
            'parallel_execution': config.getboolean('EXTERNAL_APPS', 'parallel_execution', fallback=True),
            'added': {
                'enabled': config.getboolean('EXTERNAL_APPS', 'hook_added_enabled', fallback=False),
                'command': config.get('EXTERNAL_APPS', 'hook_added_command', fallback=''),
                'show_console': config.getboolean('EXTERNAL_APPS', 'hook_added_show_console', fallback=False),
                'key_mapping': {
                    'ext1': config.get('EXTERNAL_APPS', 'hook_added_key1', fallback='ext1'),
                    'ext2': config.get('EXTERNAL_APPS', 'hook_added_key2', fallback='ext2'),
                    'ext3': config.get('EXTERNAL_APPS', 'hook_added_key3', fallback='ext3'),
                    'ext4': config.get('EXTERNAL_APPS', 'hook_added_key4', fallback='ext4'),
                },
            },
            'started': {
                'enabled': config.getboolean('EXTERNAL_APPS', 'hook_started_enabled', fallback=False),
                'command': config.get('EXTERNAL_APPS', 'hook_started_command', fallback=''),
                'show_console': config.getboolean('EXTERNAL_APPS', 'hook_started_show_console', fallback=False),
                'key_mapping': {
                    'ext1': config.get('EXTERNAL_APPS', 'hook_started_key1', fallback='ext1'),
                    'ext2': config.get('EXTERNAL_APPS', 'hook_started_key2', fallback='ext2'),
                    'ext3': config.get('EXTERNAL_APPS', 'hook_started_key3', fallback='ext3'),
                    'ext4': config.get('EXTERNAL_APPS', 'hook_started_key4', fallback='ext4'),
                },
            },
            'completed': {
                'enabled': config.getboolean('EXTERNAL_APPS', 'hook_completed_enabled', fallback=False),
                'command': config.get('EXTERNAL_APPS', 'hook_completed_command', fallback=''),
                'show_console': config.getboolean('EXTERNAL_APPS', 'hook_completed_show_console', fallback=False),
                'key_mapping': {
                    'ext1': config.get('EXTERNAL_APPS', 'hook_completed_key1', fallback='ext1'),
                    'ext2': config.get('EXTERNAL_APPS', 'hook_completed_key2', fallback='ext2'),
                    'ext3': config.get('EXTERNAL_APPS', 'hook_completed_key3', fallback='ext3'),
                    'ext4': config.get('EXTERNAL_APPS', 'hook_completed_key4', fallback='ext4'),
                },
            },
        }

        return hooks_config

    def _substitute_variables(self, command: str, context: Dict) -> str:
        """
        Substitute variables in command with actual values.

        Available variables:
        - %N: Gallery name
        - %T: Tab name
        - %p: Gallery path
        - %C: Image count
        - %g: Gallery ID
        - %j: JSON artifact path
        - %b: BBCode artifact path
        - %z: ZIP archive path
        - %s: Gallery size in bytes
        - %t: Template name
        - %e1-%e4: ext1-4 field values
        - %c1-%c4: custom1-4 field values

        Use %% to escape a literal % character (e.g., password with %j becomes %%j)
        """
        # Define substitutions - order matters for multi-char variables!
        # Process longer variable names first to avoid conflicts
        substitutions = {
            # Multi-character variables (process first)
            '%e1': str(context.get('ext1', '')),
            '%e2': str(context.get('ext2', '')),
            '%e3': str(context.get('ext3', '')),
            '%e4': str(context.get('ext4', '')),
            '%c1': str(context.get('custom1', '')),
            '%c2': str(context.get('custom2', '')),
            '%c3': str(context.get('custom3', '')),
            '%c4': str(context.get('custom4', '')),
            # Single-character variables (process after multi-char)
            '%N': context.get('gallery_name', ''),
            '%T': context.get('tab_name', ''),
            '%p': context.get('gallery_path', ''),
            '%C': str(context.get('image_count', 0)),
            '%g': context.get('gallery_id', ''),
            '%j': context.get('json_path', ''),
            '%b': context.get('bbcode_path', ''),
            '%z': context.get('zip_path', ''),
            '%s': str(context.get('size_bytes', 0)),
            '%t': context.get('template_name', ''),
        }

        # Step 1: Temporarily replace %% with a placeholder to protect escaped percent signs
        ESCAPE_PLACEHOLDER = '\x00ESCAPED_PERCENT\x00'
        result = command.replace('%%', ESCAPE_PLACEHOLDER)

        # Step 2: Sort by length (descending) to process longest matches first
        # This prevents %e1 from being partially matched as %e + "1"
        sorted_vars = sorted(substitutions.items(), key=lambda x: len(x[0]), reverse=True)

        # Step 3: Perform variable substitution
        for var, value in sorted_vars:
            result = result.replace(var, str(value))

        # Step 4: Restore escaped percent signs as literal %
        result = result.replace(ESCAPE_PLACEHOLDER, '%')

        return result

    def _execute_hook_with_config(self, hook_type: str, context: Dict, config: Dict) -> Tuple[bool, Optional[Dict]]:
        """Execute a single hook with provided config and return success status and parsed JSON output"""
        hook_config = config.get(hook_type, {})

        if not hook_config.get('enabled'):
            log(f"Hook {hook_type} is disabled, skipping", level="debug", category="hooks")
            return True, None

        command = hook_config.get('command', '').strip()
        if not command:
            log(f"Hook {hook_type} has no command configured, skipping", level="debug", category="hooks")
            return True, None

        # Check if command uses %z parameter and create temp ZIP if needed
        temp_zip_path = None
        if '%z' in command and not context.get('zip_path'):
            # Command needs a ZIP but one doesn't exist - create temporary ZIP
            gallery_path = context.get('gallery_path', '')
            if gallery_path and os.path.isdir(gallery_path):
                try:
                    from src.processing.upload_to_filehost import create_temp_zip
                    temp_zip_path = create_temp_zip(gallery_path)
                    context['zip_path'] = temp_zip_path
                    log(f"Created temporary ZIP for hook: {temp_zip_path}", level="debug", category="hooks")
                except Exception as e:
                    log(f"Failed to create temporary ZIP: {e}", level="error", category="hooks")
                    return False, None

        # Substitute variables
        final_command = self._substitute_variables(command, context)
        log(f"Executing {hook_type} hook: {final_command}", level="debug", category="hooks")

        try:
            # Determine if we should show console window
            show_console = hook_config.get('show_console', False)
            creation_flags = 0 if show_console else subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

            # Parse command into argument list to avoid shell escaping issues
            # Use shlex on Unix, manual parsing on Windows (shlex doesn't handle Windows quoting well)
            import shlex
            if sys.platform == 'win32':
                # Simple Windows-specific parsing that preserves quoted arguments
                import re
                # Split on spaces but preserve quoted strings
                cmd_args = re.findall(r'(?:[^\s"]|"(?:\\.|[^"])*")+', final_command)
                # Remove quotes from arguments
                cmd_args = [arg.strip('"') for arg in cmd_args]
            else:
                cmd_args = shlex.split(final_command)

            # Execute the command without shell to avoid special character issues
            result = subprocess.run(
                cmd_args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                creationflags=creation_flags
            )

            # Log combined stdout/stderr as single expandable message with \n line breaks
            output_parts = []
            if result.stdout:
                # Replace actual newlines with literal \n for log viewer auto-expand
                stdout_display = result.stdout.replace('\n', '\\n').rstrip('\\n')
                output_parts.append(f"[stdout]\\n{stdout_display}")
            if result.stderr:
                stderr_display = result.stderr.replace('\n', '\\n').rstrip('\\n')
                output_parts.append(f"[stderr]\\n{stderr_display}")

            combined_output = '\\n\\n'.join(output_parts) if output_parts else ""

            if result.returncode != 0:
                log(f"Hook {hook_type} failed with code {result.returncode}\\n{combined_output}", level="error", category="hooks")
                return False, None
            else:
                log(f"Hook '{hook_type}' output:\\n{combined_output}", level="info", category="hooks")
        
            # Try to parse JSON from stdout
            json_data = None
            if result.stdout.strip():
                try:
                    json_data = json.loads(result.stdout.strip())
                    log(f"Hook {hook_type} returned JSON: {json_data}", level="debug", category="hooks")
                except json.JSONDecodeError:
                    log(f"Hook {hook_type} output is not valid JSON, ignoring", level="debug", category="hooks")

            # Clean up temporary ZIP if we created one
            if temp_zip_path:
                self._remove_temp_file_with_retry(temp_zip_path)

            # Log single success message for GUI
            log(f"Hook '{hook_type}' completed successfully", level="info", category="hooks")
            return True, json_data

        except subprocess.TimeoutExpired:
            log(f"Hook {hook_type} timed out after 300 seconds", level="error", category="hooks")
            # Clean up temp ZIP on timeout
            if temp_zip_path:
                self._remove_temp_file_with_retry(temp_zip_path)
            return False, None
        except Exception as e:
            log(f"Hook {hook_type} failed with exception: {e}", level="error", category="hooks")
            # Clean up temp ZIP on error
            if temp_zip_path:
                self._remove_temp_file_with_retry(temp_zip_path)
            return False, None

    def execute_hooks(self, hook_types: List[str], context: Dict) -> Dict[str, Any]:
        """
        Execute one or more hooks (parallel or sequential based on config).

        Args:
            hook_types: List of hook types to execute ('added', 'started', 'completed')
            context: Dictionary with variables for substitution

        Returns:
            Dictionary with combined results from all hooks, including ext1-4 values
        """
        # Reload config fresh each time to pick up any settings changes
        config = self._load_config()

        # Filter to only enabled hooks
        enabled_hooks = [h for h in hook_types if config.get(h, {}).get('enabled')]

        if not enabled_hooks:
            log(f"No enabled hooks to execute from {hook_types}", level="debug", category="hooks")
            return {}

        # Execute hooks based on parallel/sequential setting
        parallel = config.get('parallel_execution', True)
        results = {}

        if parallel and len(enabled_hooks) > 1:
            log(f"Executing {len(enabled_hooks)} hooks in parallel", level="debug", category="hooks")
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(enabled_hooks)) as executor:
                futures = {executor.submit(self._execute_hook_with_config, hook_type, context, config): hook_type
                          for hook_type in enabled_hooks}

                for future in concurrent.futures.as_completed(futures):
                    hook_type = futures[future]
                    try:
                        success, json_data = future.result()
                        if json_data:
                            # Merge JSON results
                            results.update(json_data)
                    except Exception as e:
                        log(f"Hook {hook_type} raised exception: {e}", level="error", category="hooks")
        else:
            log(f"Executing {len(enabled_hooks)} hooks sequentially", level="debug", category="hooks")
            for hook_type in enabled_hooks:
                success, json_data = self._execute_hook_with_config(hook_type, context, config)
                if json_data:
                    # Later hooks can overwrite earlier ones in sequential mode
                    results.update(json_data)

        # Extract ext1-4 fields from results using configured key mappings
        ext_fields = {}

        # Merge key mappings from ALL enabled hooks (not just the first one)
        # This allows different hooks to map to different ext fields
        merged_key_mapping = {}
        for hook_type in enabled_hooks:
            hook_key_mapping = config.get(hook_type, {}).get('key_mapping', {})
            for ext_field, json_key in hook_key_mapping.items():
                # Only add if not already mapped (first hook wins for conflicts)
                if ext_field not in merged_key_mapping and json_key.strip():
                    merged_key_mapping[ext_field] = json_key.strip()
                    log(f"Added key mapping from {hook_type}: {json_key} -> {ext_field}", level="debug", category="hooks")

        # Map JSON keys to ext1-4 using merged mappings
        for ext_field, json_key in merged_key_mapping.items():
            # Use configured JSON key (e.g., "download_url") to find value in results
            if json_key in results:
                ext_fields[ext_field] = str(results[json_key])
                log(f"Mapped JSON key '{json_key}' -> {ext_field}: {results[json_key]}", level="debug", category="hooks")
            else:
                log(f"JSON key '{json_key}' not found in hook results for {ext_field}", level="debug", category="hooks")

        log(f"Hooks execution complete. Extracted fields: {ext_fields}", level="debug", category="hooks")
        return ext_fields


# Singleton instance
_hooks_executor = None


def get_hooks_executor() -> HooksExecutor:
    """Get or create the global hooks executor instance"""
    global _hooks_executor
    if _hooks_executor is None:
        _hooks_executor = HooksExecutor()
    return _hooks_executor


def execute_gallery_hooks(event_type: str, gallery_path: str, gallery_name: Optional[str] = None,
                          tab_name: str = "Main", image_count: int = 0,
                          gallery_id: Optional[str] = None, json_path: Optional[str] = None,
                          bbcode_path: Optional[str] = None, zip_path: Optional[str] = None,
                          size_bytes: int = 0, template_name: Optional[str] = None,
                          ext1: Optional[str] = None, ext2: Optional[str] = None,
                          ext3: Optional[str] = None, ext4: Optional[str] = None,
                          custom1: Optional[str] = None, custom2: Optional[str] = None,
                          custom3: Optional[str] = None, custom4: Optional[str] = None) -> Dict[str, str]:
    """
    Convenience function to execute hooks for a gallery event.

    Args:
        event_type: 'added', 'started', or 'completed'
        gallery_path: Path to gallery folder
        gallery_name: Name of gallery (defaults to folder name)
        tab_name: Tab the gallery belongs to
        image_count: Number of images in gallery
        gallery_id: Gallery ID (for completed events)
        json_path: Path to JSON artifact (for completed events)
        bbcode_path: Path to BBCode artifact (for completed events)
        zip_path: Path to ZIP archive if exists (for completed events)
        size_bytes: Gallery size in bytes
        template_name: Template name used for BBCode generation
        ext1-4: Current ext field values
        custom1-4: Current custom field values

    Returns:
        Dictionary with ext1-4 fields to update
    """
    if gallery_name is None:
        gallery_name = os.path.basename(gallery_path)

    context = {
        'gallery_name': gallery_name,
        'tab_name': tab_name,
        'gallery_path': gallery_path,
        'image_count': image_count,
        'gallery_id': gallery_id or '',
        'json_path': json_path or '',
        'bbcode_path': bbcode_path or '',
        'zip_path': zip_path or '',
        'size_bytes': size_bytes or 0,
        'template_name': template_name or '',
        'ext1': ext1 or '',
        'ext2': ext2 or '',
        'ext3': ext3 or '',
        'ext4': ext4 or '',
        'custom1': custom1 or '',
        'custom2': custom2 or '',
        'custom3': custom3 or '',
        'custom4': custom4 or '',
    }

    executor = get_hooks_executor()
    return executor.execute_hooks([event_type], context)
