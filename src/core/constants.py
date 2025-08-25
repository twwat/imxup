"""
Central constants file for ImxUp application.
All magic numbers, configuration values, and constant strings.
"""

# Application Info
APP_NAME = "ImxUp"
APP_VERSION = "0.2.4"
APP_AUTHOR = "ImxUploader"

# Network Configuration
COMMUNICATION_PORT = 27849
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
DEFAULT_PARALLEL_BATCH_SIZE = 4

# File Size Constants (Binary)
KILOBYTE = 1024
MEGABYTE = KILOBYTE * 1024
GIGABYTE = MEGABYTE * 1024
TERABYTE = GIGABYTE * 1024

# File Size Limits
MAX_LINES_PER_FILE = 2000
MAX_LINES_PER_CLASS = 500
MAX_LINES_PER_METHOD = 50

# Image Processing
MAX_DIMENSION_SAMPLES = 25
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif')

# Thumbnail Sizes (imx.to API)
THUMBNAIL_SIZES = {
    1: "100x100",
    2: "180x180", 
    3: "250x250",  # Default
    4: "300x300",
    6: "150x150"
}
DEFAULT_THUMBNAIL_SIZE = 3

# Thumbnail Formats
THUMBNAIL_FORMATS = {
    1: "JPEG 70%",
    2: "JPEG 90%",  # Default
    3: "PNG",
    4: "WEBP"
}
DEFAULT_THUMBNAIL_FORMAT = 2

# Gallery Settings
DEFAULT_PUBLIC_GALLERY = 1  # 1=public, 0=private
GALLERY_ID_LENGTH = 8

# Progress Updates
PROGRESS_UPDATE_BATCH_INTERVAL = 0.05  # seconds
PROGRESS_UPDATE_THRESHOLD = 100  # milliseconds

# URLs
BASE_API_URL = "https://api.imx.to/v1"
BASE_WEB_URL = "https://imx.to"
UPLOAD_ENDPOINT = f"{BASE_API_URL}/upload.php"

# User Agent
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0"

# HTTP Status Codes
HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_SERVER_ERROR = 500

# Queue States
QUEUE_STATE_READY = "ready"
QUEUE_STATE_QUEUED = "queued"
QUEUE_STATE_UPLOADING = "uploading"
QUEUE_STATE_COMPLETED = "completed"
QUEUE_STATE_FAILED = "failed"
QUEUE_STATE_PAUSED = "paused"
QUEUE_STATE_INCOMPLETE = "incomplete"

# Auto-Archive Settings
DEFAULT_ARCHIVE_CHECK_MINUTES = 30
MIN_ARCHIVE_CHECK_MINUTES = 5
MAX_ARCHIVE_CHECK_MINUTES = 1440  # 24 hours

# Logging
LOG_ROTATION_COUNT = 7
LOG_MAX_BYTES = 10 * MEGABYTE
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# GUI Settings
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 800
MIN_WINDOW_WIDTH = 800
MIN_WINDOW_HEIGHT = 600
TABLE_UPDATE_INTERVAL = 100  # milliseconds
ICON_SIZE = 16

# Performance Settings
MAX_CONCURRENT_UPLOADS = 10
DEFAULT_CHUNK_SIZE = 8192
MAX_QUEUE_SIZE = 1000

# File Paths
CONFIG_DIR_NAME = ".imxup"
CONFIG_FILE_NAME = "imxup.ini"
DATABASE_FILE_NAME = "imxup.db"
TEMPLATES_DIR_NAME = "templates"
GALLERIES_DIR_NAME = "galleries"
LOGS_DIR_NAME = "logs"

# Template Placeholders
TEMPLATE_PLACEHOLDERS = [
    "#folderName#",
    "#pictureCount#",
    "#width#",
    "#height#",
    "#longest#",
    "#extension#",
    "#folderSize#",
    "#galleryLink#",
    "#allImages#"
]

# Encryption
ENCRYPTION_ITERATIONS = 100000
ENCRYPTION_KEY_LENGTH = 32

# Time Formats
TIMESTAMP_FORMAT = "%H:%M:%S"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

# Error Messages
ERROR_NO_CREDENTIALS = "Failed to get credentials. Please set up credentials in the GUI or run --setup-secure first."
ERROR_NO_IMAGES = "No image files found in folder"
ERROR_GALLERY_CREATE_FAILED = "Failed to create gallery"
ERROR_UPLOAD_FAILED = "Upload failed"
ERROR_RENAME_FAILED = "Failed to rename gallery"

# Success Messages
SUCCESS_CREDENTIALS_SAVED = "Credentials saved successfully!"
SUCCESS_GALLERY_CREATED = "Gallery created successfully"
SUCCESS_UPLOAD_COMPLETE = "Upload completed successfully"
SUCCESS_RENAMED = "Gallery renamed successfully"

# Worker Thread Settings
WORKER_THREAD_POOL_SIZE = 4
WORKER_THREAD_TIMEOUT = 300  # 5 minutes

# Database Settings
DB_CONNECTION_TIMEOUT = 30
DB_LOCK_TIMEOUT = 10
DB_BATCH_SIZE = 100

# Rate Limiting
RATE_LIMIT_REQUESTS_PER_SECOND = 10
RATE_LIMIT_BURST_SIZE = 20

# Memory Management
MAX_MEMORY_CACHE_SIZE = 100 * MEGABYTE
IMAGE_CACHE_SIZE = 50  # number of images to cache

# Testing
TEST_TIMEOUT = 60
TEST_RETRY_COUNT = 3