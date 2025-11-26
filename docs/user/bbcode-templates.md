# BBCode Templates Guide

## Quick Reference

**What are BBCode Templates?**
Templates that generate formatted forum posts with gallery information, images, and download links.

**18 Available Placeholders:**
`#folderName#`, `#pictureCount#`, `#width#`, `#height#`, `#longest#`, `#extension#`, `#folderSize#`, `#galleryLink#`, `#allImages#`, `#hostLinks#`, `#custom1-4#`, `#ext1-4#`

**Conditional Syntax:**
`[if placeholder]Content[/if]` - Show content if placeholder exists
`[if placeholder=value]Content[/if]` - Show content if placeholder equals value
`[if placeholder]True[else]False[/if]` - Show different content based on condition

**Template Manager:** Settings → BBCode → **Manage Templates**

---

## What are BBCode Templates?

BBCode templates allow you to automatically generate formatted forum posts from your image galleries. They combine:

1. **Gallery Information:** Name, image count, dimensions, file size
2. **BBCode Formatting:** Bold, italics, links, images, lists
3. **Conditional Logic:** Show/hide sections based on gallery properties
4. **Custom Fields:** Your own metadata and notes
5. **File Host Links:** Download links from uploaded files

**Example Output:**
```bbcode
[b]Gallery:[/b] Summer Vacation 2024
[b]Images:[/b] 127 photos
[b]Resolution:[/b] 4000x3000 (12 MP)
[b]Format:[/b] JPG
[b]Size:[/b] 245.8 MB

[img]https://example.com/thumb1.jpg[/img]
[img]https://example.com/thumb2.jpg[/img]
[img]https://example.com/thumb3.jpg[/img]

[b]Download:[/b]
[url=https://rapidgator.net/file/abc123]Rapidgator[/url]
[url=https://k2s.cc/file/xyz789]Keep2Share[/url]
```

---

## The 18 Available Placeholders

### Gallery Information Placeholders

#### `#folderName#`
**Description:** The name of the gallery folder

**Example:**
- Folder: `Summer_Vacation_2024`
- Output: `Summer Vacation 2024`

**Usage:**
```bbcode
[b]Gallery:[/b] #folderName#
```

---

#### `#pictureCount#`
**Description:** Total number of images in gallery

**Example:**
- Gallery has 127 images
- Output: `127`

**Usage:**
```bbcode
[b]Images:[/b] #pictureCount# photos
```

**Conditional Example:**
```bbcode
[if pictureCount]
Contains #pictureCount# images
[else]
No images found
[/if]
```

---

#### `#width#`
**Description:** Average width of images in pixels

**Example:**
- Images are 4000px wide
- Output: `4000`

**Usage:**
```bbcode
[b]Resolution:[/b] #width#x#height#
```

---

#### `#height#`
**Description:** Average height of images in pixels

**Example:**
- Images are 3000px tall
- Output: `3000`

**Usage:**
```bbcode
[b]Dimensions:[/b] #width# x #height# pixels
```

---

#### `#longest#`
**Description:** Length of longest side (useful for portrait vs landscape)

**Example:**
- Landscape image 4000x3000
- Output: `4000`
- Portrait image 3000x4000
- Output: `4000`

**Usage:**
```bbcode
[b]Max Resolution:[/b] #longest#px
```

---

#### `#extension#`
**Description:** File extension of images (uppercase)

**Example:**
- Files are `.jpg`
- Output: `JPG`

**Usage:**
```bbcode
[b]Format:[/b] #extension#
```

**Conditional Example:**
```bbcode
[if extension=PNG]
  [i]Lossless PNG format[/i]
[else]
  [i]Standard JPG format[/i]
[/if]
```

---

#### `#folderSize#`
**Description:** Total size of gallery in MB

**Example:**
- Gallery is 245,823,412 bytes
- Output: `245.8 MB`

**Usage:**
```bbcode
[b]Size:[/b] #folderSize#
```

---

### Content Placeholders

#### `#galleryLink#`
**Description:** Link to original gallery location (if configured)

**Example:**
- Output: `https://example.com/galleries/summer-2024`

**Usage:**
```bbcode
[url=#galleryLink#]View Full Gallery[/url]
```

**Conditional Example:**
```bbcode
[if galleryLink]
[b]Source:[/b] [url=#galleryLink#]Original Gallery[/url]
[/if]
```

---

#### `#allImages#`
**Description:** BBCode for all images in gallery

**Example:**
```
[img]https://example.com/img1.jpg[/img]
[img]https://example.com/img2.jpg[/img]
[img]https://example.com/img3.jpg[/img]
```

**Usage:**
```bbcode
[b]Preview:[/b]
#allImages#
```

**Note:** Can generate very long output for galleries with 100+ images. Use conditionally:
```bbcode
[if pictureCount<50]
#allImages#
[else]
[i]Too many images to display (see download link)[/i]
[/if]
```

---

#### `#hostLinks#`
**Description:** Download links from file host uploads

**Example:**
```
[url=https://rapidgator.net/file/abc123]Rapidgator[/url]
[url=https://k2s.cc/file/xyz789]Keep2Share[/url]
```

**Usage:**
```bbcode
[b]Download:[/b]
#hostLinks#
```

**Conditional Example:**
```bbcode
[if hostLinks]
[b]Download Links:[/b]
#hostLinks#
[else]
[i]Uploading in progress...[/i]
[/if]
```

---

### Custom Field Placeholders

#### `#custom1#` through `#custom4#`
**Description:** User-defined custom fields for any metadata

**Example Use Cases:**
- `#custom1#` = Photographer name
- `#custom2#` = Camera model
- `#custom3#` = Location/event
- `#custom4#` = Copyright/license

**Setting Custom Fields:**
1. Right-click gallery → **Properties**
2. Navigate to **Custom Fields** tab
3. Enter values in Custom 1-4 fields

**Usage:**
```bbcode
[b]Photographer:[/b] #custom1#
[b]Camera:[/b] #custom2#
[b]Location:[/b] #custom3#
[b]License:[/b] #custom4#
```

**Conditional Example:**
```bbcode
[if custom1]
[i]Photo by #custom1#[/i]
[/if]
```

---

### Extension Field Placeholders

#### `#ext1#` through `#ext4#`
**Description:** Additional extension fields for advanced metadata

**Example Use Cases:**
- `#ext1#` = ISO rating/content rating
- `#ext2#` = Tags/keywords
- `#ext3#` = Date taken
- `#ext4#` = Series/collection name

**Setting Extension Fields:**
Same as custom fields - Properties → Custom Fields tab

**Usage:**
```bbcode
[b]Rating:[/b] #ext1#
[b]Tags:[/b] #ext2#
[b]Date:[/b] #ext3#
[b]Series:[/b] #ext4#
```

---

## Conditional Logic Syntax

### Basic Conditional: `[if placeholder]`

**Syntax:**
```bbcode
[if placeholder]
  Content to show if placeholder exists (not empty)
[/if]
```

**Example 1: Show section only if images exist**
```bbcode
[if pictureCount]
  [b]Gallery contains #pictureCount# images[/b]
[/if]
```

**Example 2: Show download links only if available**
```bbcode
[if hostLinks]
  [b]Download:[/b]
  #hostLinks#
[/if]
```

**Example 3: Show photographer credit if provided**
```bbcode
[if custom1]
  [i]Photography by #custom1#[/i]
[/if]
```

---

### Conditional with Else: `[if placeholder][else][/if]`

**Syntax:**
```bbcode
[if placeholder]
  Content if exists
[else]
  Content if missing
[/if]
```

**Example 1: Gallery status**
```bbcode
[if hostLinks]
  [b]Status:[/b] [color=green]Available for download[/color]
[else]
  [b]Status:[/b] [color=orange]Upload in progress[/color]
[/if]
```

**Example 2: Image format indicator**
```bbcode
[if extension=PNG]
  [img]https://example.com/icon-lossless.png[/img]
[else]
  [img]https://example.com/icon-standard.png[/img]
[/if]
```

**Example 3: Size warning**
```bbcode
[if pictureCount>100]
  [b][color=red]Large gallery! May take time to load.[/color][/b]
[else]
  [b]Gallery size:[/b] #pictureCount# images
[/if]
```

---

### Equality Conditional: `[if placeholder=value]`

**Syntax:**
```bbcode
[if placeholder=value]
  Content to show if placeholder equals value exactly
[/if]
```

**Example 1: Format-specific icons**
```bbcode
[if extension=JPG]
  [img]https://example.com/jpg-icon.png[/img]
[/if]
[if extension=PNG]
  [img]https://example.com/png-icon.png[/img]
[/if]
[if extension=GIF]
  [img]https://example.com/gif-icon.png[/img]
[/if]
```

**Example 2: Special handling for specific count**
```bbcode
[if pictureCount=1]
  [b]Single image[/b]
[else]
  [b]#pictureCount# images[/b]
[/if]
```

**Example 3: Content rating badges**
```bbcode
[if ext1=SFW]
  [img]https://example.com/badge-sfw.png[/img]
[/if]
[if ext1=NSFW]
  [img]https://example.com/badge-nsfw.png[/img]
[/if]
```

---

## Example Templates

### Example 1: Simple Gallery Post

**Template:**
```bbcode
[b]#folderName#[/b]

[b]Images:[/b] #pictureCount#
[b]Resolution:[/b] #width#x#height#
[b]Format:[/b] #extension#
[b]Size:[/b] #folderSize#

[if hostLinks]
[b]Download:[/b]
#hostLinks#
[/if]
```

**Output:**
```bbcode
[b]Summer Vacation 2024[/b]

[b]Images:[/b] 127
[b]Resolution:[/b] 4000x3000
[b]Format:[/b] JPG
[b]Size:[/b] 245.8 MB

[b]Download:[/b]
[url=https://rapidgator.net/file/abc123]Rapidgator[/url]
[url=https://k2s.cc/file/xyz789]Keep2Share[/url]
```

---

### Example 2: Advanced Gallery Post with Thumbnails

**Template:**
```bbcode
[center][size=150][b]#folderName#[/b][/size][/center]

[table]
[tr][td][b]Images:[/b][/td][td]#pictureCount# photos[/td][/tr]
[tr][td][b]Resolution:[/b][/td][td]#width# x #height# (#longest#px max)[/td][/tr]
[tr][td][b]Format:[/b][/td][td]#extension#[/td][/tr]
[tr][td][b]Size:[/b][/td][td]#folderSize#[/td][/tr]
[if custom1]
[tr][td][b]Photographer:[/b][/td][td]#custom1#[/td][/tr]
[/if]
[if custom3]
[tr][td][b]Location:[/b][/td][td]#custom3#[/td][/tr]
[/if]
[/table]

[hr]

[if pictureCount<20]
[b]Preview:[/b]
#allImages#
[else]
[b]Preview:[/b] [i](Too many images - see download)[/i]
[/if]

[hr]

[if hostLinks]
[b][size=120]Download Links:[/size][/b]
#hostLinks#
[else]
[color=orange][i]Upload in progress - check back soon![/i][/color]
[/if]
```

---

### Example 3: Minimalist Template

**Template:**
```bbcode
[b]#folderName#[/b] - #pictureCount# images (#folderSize#)
#hostLinks#
```

**Output:**
```bbcode
[b]Summer Vacation 2024[/b] - 127 images (245.8 MB)
[url=https://rapidgator.net/file/abc123]Rapidgator[/url]
[url=https://k2s.cc/file/xyz789]Keep2Share[/url]
```

---

### Example 4: Content Rating Template

**Template:**
```bbcode
[b]Title:[/b] #folderName#

[if ext1=SFW]
[img]https://example.com/badge-sfw.png[/img]
[b][color=green]Safe For Work[/color][/b]
[/if]

[if ext1=NSFW]
[img]https://example.com/badge-nsfw.png[/img]
[b][color=red]Not Safe For Work (18+)[/color][/b]
[spoiler]
#allImages#
[/spoiler]
[/if]

[b]Stats:[/b] #pictureCount# images | #width#x#height# | #folderSize#

[b]Download:[/b]
#hostLinks#
```

---

### Example 5: Series Collection Template

**Template:**
```bbcode
[center][size=150][b]#ext4#[/b][/size]
[size=120]Episode: #folderName#[/size][/center]

[quote]
[b]Series:[/b] #ext4#
[b]Episode:[/b] #folderName#
[b]Images:[/b] #pictureCount#
[b]Quality:[/b] #width#x#height# (#longest#px)
[b]Format:[/b] #extension#

[if custom1]
[b]Creator:[/b] #custom1#
[/if]
[if ext2]
[b]Tags:[/b] #ext2#
[/if]
[/quote]

[hr]

[b]Preview Images:[/b]
[if pictureCount<15]
#allImages#
[else]
[i]High image count - download to view all[/i]
[/if]

[hr]

[b]Download Options:[/b]
#hostLinks#

[if ext1]
[b]Rating:[/b] #ext1#
[/if]
```

---

## Creating Custom Templates

### Step 1: Open Template Manager

1. Go to **Settings → BBCode → Manage Templates**
2. Or use keyboard shortcut: **Ctrl+T**

### Step 2: Create New Template

1. Click **New Template** button
2. Enter template name (e.g., "My Custom Template")
3. Click **OK**

### Step 3: Build Your Template

**Use Insert Buttons:**
- Click placeholder buttons on right side
- Inserts placeholder at cursor position

**Or Type Manually:**
- Type placeholders with `#` symbols
- Syntax highlighting shows recognized placeholders (yellow background)

**Add BBCode Formatting:**
```bbcode
[b]Bold text[/b]
[i]Italic text[/i]
[u]Underlined text[/u]
[url=link]Link text[/url]
[img]image-url[/img]
[color=red]Colored text[/color]
[size=150]Larger text[/size]
[center]Centered text[/center]
[quote]Quoted text[/quote]
[code]Code block[/code]
[list][*]Item 1[*]Item 2[/list]
[table][tr][td]Cell[/td][/tr][/table]
```

### Step 4: Add Conditional Logic

**Use [if] Helper:**
1. Click **[if] Helper** button
2. Select placeholder from dropdown
3. Choose condition type:
   - "Check if exists (non-empty)"
   - "Check if equals value"
4. Optionally include `[else]` clause
5. Click **Insert**

**Manual Conditional:**
```bbcode
[if pictureCount]
  Content when exists
[else]
  Content when missing
[/if]
```

### Step 5: Validate Syntax

1. Click **Validate Syntax** button
2. Fix any errors shown:
   - Unmatched `[if]`/`[/if]` tags
   - Missing closing BBCode tags
   - Invalid conditional syntax
   - Orphaned `[else]` tags

### Step 6: Save Template

1. Click **Save Template** button
2. Template saved to: `templates/[name].template.txt`
3. Available for use in BBCode viewer

---

## Template Validation

### Common Syntax Errors

#### Error 1: Unmatched Conditional Tags

**Error Message:** "Unmatched conditional tags: 2 [if] but 1 [/if]"

**Cause:** Missing closing `[/if]` tag

**Example:**
```bbcode
[if pictureCount]
  Line 1
[/if]

[if folderName]
  Line 2
← Missing [/if] here!
```

**Fix:**
```bbcode
[if pictureCount]
  Line 1
[/if]

[if folderName]
  Line 2
[/if]
```

---

#### Error 2: Invalid [if] Syntax

**Error Message:** "Invalid [if] syntax: '[if pictureCount > 50]'"

**Cause:** Unsupported operator (only `=` or existence check supported)

**Example:**
```bbcode
[if pictureCount > 50]  ← Wrong: > not supported
[if pictureCount<100]   ← Wrong: < not supported
[if pictureCount = 50]  ← Wrong: spaces around =
```

**Fix:**
```bbcode
[if pictureCount=50]    ← Correct: equality check
[if pictureCount]       ← Correct: existence check
```

---

#### Error 3: Unmatched BBCode Tags

**Error Message:** "Unmatched [url] tags: 3 opening but 2 closing"

**Cause:** Missing `[/url]` closing tag

**Example:**
```bbcode
[url=link1]Link 1[/url]
[url=link2]Link 2
[url=link3]Link 3[/url]
```

**Fix:**
```bbcode
[url=link1]Link 1[/url]
[url=link2]Link 2[/url]
[url=link3]Link 3[/url]
```

---

#### Error 4: Orphaned [else] Tag

**Error Message:** "Line 15: [else] tag found outside of conditional block"

**Cause:** `[else]` used without surrounding `[if]`/`[/if]`

**Example:**
```bbcode
Line 10: Some text
Line 11: [else]  ← Not inside [if] block!
Line 12: More text
```

**Fix:**
```bbcode
[if pictureCount]
  Has images
[else]
  No images
[/if]
```

---

## Template Manager Features

### Syntax Highlighting

**Placeholders:** Yellow/gold background
```
#folderName#  ← Highlighted in yellow
```

**Conditional Tags:** Blue background
```
[if pictureCount]  ← Highlighted in blue
[else]             ← Highlighted in blue
[/if]              ← Highlighted in blue
```

**Unrecognized Text:** Normal (no highlighting)

### Insert Placeholder Buttons

**Layout:** 2 columns, 9 rows

**Buttons:**
- Gallery Name → `#folderName#`
- All Images → `#allImages#`
- Host Links → `#hostLinks#`
- Height → `#height#`
- Picture Count → `#pictureCount#`
- Width → `#width#`
- Folder Size → `#folderSize#`
- Longest Side → `#longest#`
- Custom 1 → `#custom1#`
- Gallery Link → `#galleryLink#`
- Custom 2 → `#custom2#`
- Extension → `#extension#`
- Custom 3 → `#custom3#`
- Ext 1 → `#ext1#`
- Custom 4 → `#custom4#`
- Ext 2 → `#ext2#`
- Ext 3 → `#ext3#`
- Ext 4 → `#ext4#`

**Insert Conditional Buttons:**
- [if] Helper → Opens conditional dialog
- [else] → Inserts `[else]` tag
- [/if] → Inserts `[/if]` closing tag

### Template Operations

**New Template:**
- Creates blank template
- Prompts for name
- Opens in editor

**Rename Template:**
- Select template from list
- Click Rename
- Enter new name
- Updates file automatically

**Delete Template:**
- Select template from list
- Click Delete
- Confirms deletion
- Cannot delete "default" template

**Save Template:**
- Enabled when content changes
- Validates syntax before saving (optional)
- Saves to `templates/[name].template.txt`

### Unsaved Changes Warning

**Triggers:**
- Switching to different template
- Closing Template Manager
- Creating new template

**Options:**
- **Yes:** Save changes and continue
- **No:** Discard changes and continue
- **Cancel:** Stay on current template

---

## Using Templates in BBCode Viewer

### Step 1: Generate BBCode

1. Select gallery in table
2. Right-click → **View BBCode**
3. Or use keyboard shortcut: **Ctrl+B**

### Step 2: Select Template

**Dropdown:** Top of BBCode Viewer dialog

**Available Templates:**
- default (built-in)
- Your custom templates (alphabetically sorted)

**Change Template:**
- Select from dropdown
- BBCode regenerates automatically
- No need to close/reopen dialog

### Step 3: Copy BBCode

**Copy Button:**
- Copies all BBCode to clipboard
- Paste into forum post editor

**Select All:**
- Ctrl+A to select all text
- Ctrl+C to copy

### Step 4: Preview (if forum supports)

**Most forums show preview:**
- Paste BBCode
- Click "Preview" button
- Verify formatting before posting

---

## Best Practices

### 1. Start Simple

**Beginner Template:**
```bbcode
[b]#folderName#[/b]
#pictureCount# images | #folderSize#
#hostLinks#
```

**Then Add Gradually:**
- Add more placeholders
- Include formatting (colors, sizes)
- Add conditionals
- Test after each change

### 2. Use Conditionals for Optional Fields

**Good:**
```bbcode
[if custom1]
Photo by: #custom1#
[/if]
```

**Bad:**
```bbcode
Photo by: #custom1#
← Shows "Photo by: " even if empty
```

### 3. Validate Before Saving

- Always click **Validate Syntax**
- Fix all errors before saving
- Test with actual gallery

### 4. Test with Different Galleries

**Test Cases:**
- Gallery with 5 images
- Gallery with 100+ images
- Gallery with custom fields filled
- Gallery with custom fields empty
- Gallery with file host links
- Gallery without file host links

### 5. Backup Your Templates

**Location:** `templates/*.template.txt`

**Backup:**
```bash
cp -r templates templates.backup
```

**Or use version control:**
```bash
git add templates/
git commit -m "Add custom template"
```

---

## Troubleshooting Templates

### Placeholder Showing Literally

**Symptom:** `#folderName#` appears in output instead of gallery name

**Causes:**
1. Typo in placeholder name (e.g., `#foldername#` instead of `#folderName#`)
2. Gallery data not loaded
3. Field empty/not set

**Solutions:**
1. Check spelling (case-sensitive!)
2. Right-click gallery → Re-analyze
3. Verify field has value in Properties

### Conditional Not Working

**Symptom:** Content shows when it shouldn't, or vice versa

**Debug:**
```bbcode
[if pictureCount]
  TRUE: #pictureCount#
[else]
  FALSE: pictureCount is empty
[/if]
```

**Common Issues:**
- Extra spaces in tag: `[if pictureCount ]` ← Wrong
- Wrong syntax: `[if #pictureCount#]` ← Wrong (no # in condition)
- Missing data: Check gallery Properties

### BBCode Not Rendering on Forum

**Forum Differences:**
- Some forums disable certain BBCode tags
- Custom tags may not be supported
- Size limits on [img] tags

**Test Forum Support:**
```bbcode
[b]Bold[/b] [i]Italic[/i] [u]Underline[/u]
[url=http://google.com]Link[/url]
[img]http://example.com/test.jpg[/img]
```

**Fallback:**
- Use simpler template
- Remove unsupported tags
- Use plain text links

---

## Advanced Techniques

### Nested Conditionals

**Syntax:**
```bbcode
[if pictureCount]
  Has images
  [if extension=PNG]
    PNG format
  [else]
    Other format
  [/if]
[/if]
```

**Note:** Validator may not support deep nesting (2 levels max recommended)

### Multi-Value Checks

**Using Multiple [if] Blocks:**
```bbcode
[if extension=JPG]JPG format[/if]
[if extension=PNG]PNG format[/if]
[if extension=GIF]GIF format[/if]
[if extension=WEBP]WEBP format[/if]
```

**Fallback with [else]:**
```bbcode
[if extension=PNG]
  Lossless PNG
[else]
  [if extension=JPG]
    Standard JPG
  [else]
    Unknown format
  [/if]
[/if]
```

### Dynamic Styling Based on Size

**Example:**
```bbcode
[if pictureCount<10]
  [color=green][b]Small gallery[/b][/color]
[/if]

[if pictureCount=50]
  [color=orange][b]Medium gallery[/b][/color]
[/if]

[if pictureCount>100]
  [color=red][b]Large gallery![/b][/color]
[/if]
```

**Note:** Only equality (`=`) supported, not `<` or `>`. Use multiple `=` checks for ranges.

---

## Placeholder Reference Table

| Placeholder | Type | Description | Example Output |
|------------|------|-------------|----------------|
| `#folderName#` | Text | Gallery folder name | `Summer Vacation 2024` |
| `#pictureCount#` | Number | Total image count | `127` |
| `#width#` | Number | Average width (px) | `4000` |
| `#height#` | Number | Average height (px) | `3000` |
| `#longest#` | Number | Longest side (px) | `4000` |
| `#extension#` | Text | File extension | `JPG` |
| `#folderSize#` | Text | Total size with unit | `245.8 MB` |
| `#galleryLink#` | URL | Original gallery link | `https://...` |
| `#allImages#` | BBCode | All image tags | `[img]...[/img]` |
| `#hostLinks#` | BBCode | Download links | `[url=...]...[/url]` |
| `#custom1#` | Text | Custom field 1 | (user-defined) |
| `#custom2#` | Text | Custom field 2 | (user-defined) |
| `#custom3#` | Text | Custom field 3 | (user-defined) |
| `#custom4#` | Text | Custom field 4 | (user-defined) |
| `#ext1#` | Text | Extension field 1 | (user-defined) |
| `#ext2#` | Text | Extension field 2 | (user-defined) |
| `#ext3#` | Text | Extension field 3 | (user-defined) |
| `#ext4#` | Text | Extension field 4 | (user-defined) |

---

## Conditional Syntax Reference

| Syntax | Description | Example |
|--------|-------------|---------|
| `[if placeholder]` | Check if exists (not empty) | `[if pictureCount]Has images[/if]` |
| `[if placeholder=value]` | Check if equals value | `[if extension=PNG]PNG format[/if]` |
| `[if placeholder][else][/if]` | If-else block | `[if hostLinks]Available[else]Uploading[/if]` |
| `[/if]` | Close conditional | Required for every `[if]` |

**Important Notes:**
- Case-sensitive placeholder names
- No spaces around `=` in equality checks
- No `#` symbols in conditional tags
- Must close all `[if]` tags with `[/if]`

---

## Getting Help

**Documentation:**
- Template Manager: Settings → BBCode → Manage Templates → Help
- Placeholder list: Click **?** icon in Template Manager
- This guide: `docs/user/bbcode-templates.md`

**Support:**
- GitHub Issues: Report template bugs
- Community Forums: Share templates

**Related Guides:**
- `docs/QUICK_START_GUI.md` - Getting started
- `docs/user/multi-host-upload.md` - File host uploads
- `docs/user/troubleshooting.md` - Common issues

---

**Happy template crafting!** 🎨
