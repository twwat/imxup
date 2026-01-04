# Troubleshooting

Quick fixes for common problems.

---

## Upload Failed

**Check the error message** in the Status column. Common causes:

| Error | Solution |
|-------|----------|
| **Authentication failed** | Re-enter credentials in Settings → Credentials |
| **Connection timeout** | Check your internet connection |
| **Server error (5xx)** | Wait a few minutes and retry |
| **Rate limited** | Wait 10-15 minutes before retrying |

**To retry:** Right-click the failed gallery and select **Retry Upload**.

---

## Gallery Stuck on "Uploading"

- Click **Pause All** then **Start All** to reset
- Check your internet connection
- If it persists, remove the gallery and re-add it

---

## BBCode Not Copying

- Make sure the upload is complete (green Completed status)
- Right-click the gallery and select **Copy BBCode**
- Check that a template is selected in Settings

---

## File Host Upload Failed

- Click **Test Connection** in Settings → File Hosts to verify credentials
- Check if your API key has expired
- Some hosts require premium accounts for uploads
- Try uploading to one host at a time to isolate the problem

---

## Drag and Drop Not Working

- Make sure you're dragging **folders**, not individual images
- Try the **Add Folder** button instead
- Restart the application if it still doesn't work

---

## Application Running Slowly

- Click **Clear Completed** to remove finished galleries
- Close tabs you're not using
- If you have 100+ galleries queued, upload in smaller batches

---

## Can't Find My Settings

Settings are stored in your user folder. If you need to reset:

- Close IMXuploader
- Delete the `.imxup` folder in your home directory
- Restart and reconfigure your credentials

---

## Still Having Problems?

Check the **Log Output** panel on the right side of the window for detailed error messages. This often reveals the specific issue.
