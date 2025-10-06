# imx.to Gallery Uploader

A Python script to upload folders of images as galleries to imx.to

## Setup

1. Install requirements:
   ```
   pip install -r requirements.txt
   ```

## How To Run (GUI)

```
python imxup.py --gui
```

## Command-line Usage

```
python imxup.py path/to/image/folder/to/upload
```

Optional parameters:
- `--name GALLERY_NAME` - Set a name for the gallery
- `--template TEMPLATE_NAME` or `-t TEMPLATE_NAME` - Use a specific template for bbcode generation

Example:
```
python imxup.py ./test_images --name "My Vacation Photos"
python imxup.py ./test_images --template "Detailed Example"
```

## Features

- Uploads all images from a folder as a single gallery
- Supports common image formats (jpg, png, gif, bmp, webp)
- Returns gallery URL and individual image URLs
- Handles errors gracefully
- Template-based bbcode generation with customizable formats

## BBCode Templates

The system generates bbcode files using templates. You can create custom templates in the `~/imxup_galleries` folder by creating files that start with `.template`.

### Available Placeholders

- `#folderName#` - Name of the gallery
- `#width#` - Average width of photos in pixels
- `#height#` - Average height of photos in pixels  
- `#longest#` - Longest side in pixels (width or height)
- `#extension#` - Most common image format (JPG, PNG, etc.)
- `#pictureCount#` - Number of images in gallery
- `#folderSize#` - Total size of gallery (e.g. "52.9 MB")
- `#galleryLink#` - URL for gallery (e.g. https://imx.to/g/gallery_id)
- `#allImages#` - BBCode for all images
- `#custom1#` - Custom data provided by user (1 of 4)
- `#custom2#` - Custom data provided by user (2 of 4)
- `#custom3#` - Custom data provided by user (3 of 4)
- `#custom4#` - Custom data provided by user (4 of 4)

### Default Template

The default template is:
```
#folderName#
#allImages#
```

### Creating Custom Templates

Create a file in `~/.imxup` with a name ending with `.template.txt`, for example:
- `My Template.template.txt`
- `Detailed Format.template.txt`

Example template:
```
Gallery: #folderName#
Images: #pictureCount# (#extension# format)
Size: #folderSize#
Dimensions: #width#x#height# (longest side: #longest#)
Gallery Link: #galleryLink#

#allImages#
```

### GUI Template Selection

In the GUI, you can select a template from the "BBCode Template" dropdown in the Settings panel. The selected template will be used for all galleries added to the queue.

#### Managing Templates

Click the "Manage BBCode Templates" button in the Settings panel to:
- View all available templates
- Create new templates
- Edit existing templates with a rich text editor
- Rename templates
- Delete templates (except the default template)
- Insert placeholders using convenient buttons

The template editor includes buttons for all available placeholders:
- Gallery Name (`#folderName#`)
- Width (`#width#`)
- Height (`#height#`)
- Longest Side (`#longest#`)
- Extension (`#extension#`)
- Picture Count (`#pictureCount#`)
- Folder Size (`#folderSize#`)
- Gallery Link (`#galleryLink#`)
- All Images (`#allImages#`)

### Command Line Template Selection

Use the `--template` or `-t` option to specify a template:

```bash
python imxup.py ./test_images --template "Detailed Example"
```
