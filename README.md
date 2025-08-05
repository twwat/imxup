# imx.to Gallery Uploader

A Python script to upload folders of images as galleries to imx.to

## Setup

1. Install requirements:
   ```
   pip install -r requirements.txt
   ```

2. Add your imx.to API key to `.env`:
   ```
   IMX_API=your_api_key_here
   ```

## Usage

```
python imxup.py path/to/image/folder
```

Optional parameters:
- `--name GALLERY_NAME` - Set a name for the gallery

Example:
```
python imxup.py ./test_images --name "My Vacation Photos"
```

## Features

- Uploads all images from a folder as a single gallery
- Supports common image formats (jpg, png, gif, bmp, webp)
- Returns gallery URL and individual image URLs
- Handles errors gracefully