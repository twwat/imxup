#!/usr/bin/env python3
"""
Multi-host file uploader for Keep2Share, Tezfiles, and Fboom
Uploads files using their API v2

Usage:
  python upload_multi_host.py <filename> --service k2s --api-key YOUR_KEY
  python upload_multi_host.py <filename> -s tez -k YOUR_KEY
  python upload_multi_host.py <filename> -s fb -k YOUR_KEY

Supported services:
  k2s, keep2share  -> https://keep2share.cc/api/v2/
  tez, tezfiles    -> https://tezfiles.com/api/v2/
  fb, fboom        -> https://fboom.me/api/v2/

This script outputs the raw JSON response from the service, which you can
map to ext1-4 fields in imxup's External Apps JSON mapping dialog.

For imxup External Apps integration:
  Command: python "path/to/upload_multi_host.py" "%p" --service k2s --api-key YOUR_KEY
  Then use "Map JSON Keys..." to choose which fields to use
"""

import sys
import json
import requests
import argparse
from pathlib import Path

# Service configurations
SERVICES = {
    "k2s": {
        "name": "Keep2Share",
        "api_base": "https://keep2share.cc/api/v2",
        "aliases": ["k2s", "keep2share"]
    },
    "tez": {
        "name": "Tezfiles",
        "api_base": "https://tezfiles.com/api/v2",
        "aliases": ["tez", "tezfiles"]
    },
    "fb": {
        "name": "Fboom",
        "api_base": "https://fboom.me/api/v2",
        "aliases": ["fb", "fboom"]
    }
}


def get_service_config(service_identifier):
    """
    Get service configuration by identifier (k2s, tez, fb, or full name)
    Returns (service_key, config_dict) or (None, None) if not found
    """
    service_lower = service_identifier.lower()

    # Check each service's aliases
    for service_key, config in SERVICES.items():
        if service_lower in [alias.lower() for alias in config["aliases"]]:
            return service_key, config

    return None, None


def check_status(response_json, action, service_name):
    """Check API response status"""
    if response_json.get("status") == "success":
        print(f"===> [{service_name}] {action} is OK", file=sys.stderr)
        return True
    else:
        print(f"===> [{service_name}] {action} is FAILED", file=sys.stderr)
        print(f"[message]: {response_json.get('message', 'Unknown error')}", file=sys.stderr)
        print(f"[code]: {response_json.get('code', 'N/A')}", file=sys.stderr)
        sys.exit(1)


def get_upload_form_data(session, api_base, access_token, service_name):
    """Get upload form data from API"""
    try:
        response = session.post(
            f"{api_base}/getUploadFormData",
            json={"access_token": access_token},
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        check_status(data, "Getting form data", service_name)

        return {
            "form_action": data.get("form_action"),
            "file_field": data.get("file_field"),
            "ajax": data.get("form_data", {}).get("ajax"),
            "params": data.get("form_data", {}).get("params"),
            "signature": data.get("form_data", {}).get("signature")
        }
    except requests.RequestException as e:
        print(f"Network error getting form data: {e}", file=sys.stderr)
        sys.exit(1)


def upload_file(session, file_path, form_data, service_name):
    """Upload file using form data"""
    try:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Prepare multipart form data
        with open(file_path, 'rb') as f:
            files = {
                form_data["file_field"]: (file_path.name, f, 'application/octet-stream')
            }

            fields = {
                "ajax": form_data["ajax"],
                "signature": form_data["signature"],
                "params": form_data["params"]
            }

            response = session.post(
                form_data["form_action"],
                files=files,
                data=fields,
                timeout=300  # 5 minutes for large files
            )
            response.raise_for_status()

        upload_result = response.json()
        check_status(upload_result, "Uploading file to server", service_name)

        return upload_result

    except FileNotFoundError as e:
        print(f"File error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"Network error uploading file: {e}", file=sys.stderr)
        sys.exit(1)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Multi-host file uploader for Keep2Share, Tezfiles, and Fboom",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python upload_multi_host.py image.jpg --service k2s --api-key YOUR_KEY
  python upload_multi_host.py video.mp4 -s tez -k YOUR_KEY
  python upload_multi_host.py archive.zip -s fboom -k YOUR_KEY

Supported services:
  k2s, keep2share  -> Keep2Share (https://keep2share.cc)
  tez, tezfiles    -> Tezfiles (https://tezfiles.com)
  fb, fboom        -> Fboom (https://fboom.me)
"""
    )

    parser.add_argument(
        "file",
        help="File to upload"
    )

    parser.add_argument(
        "-s", "--service",
        required=True,
        help="File hosting service (k2s, tez, fb, or full names)"
    )

    parser.add_argument(
        "-k", "--api-key",
        required=True,
        help="API access token for the service"
    )

    return parser.parse_args()


def main():
    """Main entry point"""
    # Parse arguments
    args = parse_arguments()

    # Validate service
    service_key, service_config = get_service_config(args.service)
    if not service_config:
        print(f"Error: Unknown service '{args.service}'", file=sys.stderr)
        print(f"Supported services: {', '.join([', '.join(s['aliases']) for s in SERVICES.values()])}", file=sys.stderr)
        sys.exit(1)

    # Validate file path
    file_path = Path(args.file)
    if file_path.is_dir():
        print(f"Error: {file_path} is a directory. Please provide a file.", file=sys.stderr)
        sys.exit(1)

    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    # Display upload info
    service_name = service_config["name"]
    api_base = service_config["api_base"]

    #print(f"===== {service_name} File Uploader =====", file=sys.stderr)
    print(f"===== Service: {service_name} Uploader  (API Base: {api_base})", file=sys.stderr)
    print(f"File: {file_path.name} ({file_path.stat().st_size / 1024 / 1024:.2f} MB)", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    session = requests.Session()

    # Step 1: Get upload form data
    print(f"Getting upload form data for: {file_path.name}", file=sys.stderr)
    form_data = get_upload_form_data(session, api_base, args.api_key, service_name)

    # Step 2: Upload file
    print(f"Uploading file: {file_path.name}", file=sys.stderr)
    upload_response = upload_file(session, file_path, form_data, service_name)

    # Step 3: Output the raw JSON response
    # This is what imxup will capture and you can map the fields you want
    print(json.dumps(upload_response, indent=2))

    # Debug info to stderr (won't interfere with JSON output)
    print(f"\n===== Upload Complete! =====", file=sys.stderr)
    print(f"Service: {service_name}", file=sys.stderr)
    print(f"Available JSON fields for imxup mapping:", file=sys.stderr)
    for key in upload_response.keys():
        value = upload_response[key]
        # Truncate long values for display
        value_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
        print(f"  - {key}: {value_str}", file=sys.stderr)
    print(f"[{service_name}] Finished uploading '{file_path.name}' ({file_path.stat().st_size / 1024 / 1024:.2f} MB) to {service_name}", file=sys.stderr)

if __name__ == "__main__":
    main()
