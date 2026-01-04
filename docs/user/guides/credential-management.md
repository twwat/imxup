# Credential Management Guide

## Quick Reference

**Version:** v0.6.16
**Feature:** Secure storage and management of passwords and authentication keys
**Storage:** OS Keyring (primary) + Encrypted fallback (Fernet)
**Supported Hosts:** IMX.to + 7 file hosting services
**Last Updated:** 2026-01-03

---

## Overview

Credential management in imxup is designed to be secure and transparent. Whether you're logging into imx.to or configuring multiple file hosts, your credentials are encrypted and stored securely—never sent to third parties, never stored in plain text.

This guide covers:
- What credentials imxup stores
- Where and how they're stored
- How to set them up
- Security practices
- What to do if something goes wrong

---

## Credential Types

IMXuploader handles four types of credentials, each with different authentication methods:

### 1. IMX.to Username/Password

**What it is:** Your imx.to login credentials for uploading image galleries.

**Storage:** OS Keyring or encrypted config file
- **Used for:** Creating new galleries, setting visibility (public/private), retrieving gallery IDs
- **Format:** Username and password separately
- **Expiry:** Session-based (no manual refresh needed)

**Setup:**
1. Open **Settings** (Ctrl+,)
2. Enter your imx.to username and password
3. Click **Test Connection**
4. Credentials are automatically saved to OS keyring

---

### 2. File Host API Keys

**Hosts:** Fileboom, Keep2Share, Tezfiles, Katfile

**What it is:** Permanent authentication token from your file host account.

**Storage:** OS Keyring
- **Used for:** Uploading files to the file host
- **Format:** Single API key/token string
- **Expiry:** Never (API keys don't expire)
- **Security:** API keys have the same access as your account—treat them like passwords

**Obtaining Your API Key:**
1. Log into your file host account (e.g., rapidgator.net)
2. Navigate to **Account Settings** or **API Settings**
3. Copy your API Key
4. In imxup: **Settings → File Hosts → [Host] → Credentials**
5. Paste the API key and click **Test Connection**

**Example Hosts:**
- **Fileboom** (fboom.me): Account → API Settings → Copy API Key
- **Keep2Share** (k2s.cc): Account → API → Show API Key
- **Tezfiles** (tezfiles.com): Account → My API Key
- **Katfile** (katfile.com): Account → API Settings

---

### 3. Rapidgator Token Login

**Host:** Rapidgator (rapidgator.net)

**What it is:** Username:password that imxup converts to a temporary access token.

**Storage:** OS Keyring (credentials) + `~/.imxup/token_cache.db` (token)
- **Used for:** Uploading files to Rapidgator
- **Format:** `username:password` (credentials stored separately from token)
- **Token Expiry:** 24 hours (auto-refresh before expiry)
- **Security:** Credentials never sent to imxup servers; only used for Rapidgator API

**How it Works:**
1. You provide username:password in Settings
2. imxup logs in to Rapidgator and receives a 24-hour token
3. Token is cached locally (expires after 24 hours)
4. Before expiry, imxup auto-refreshes the token
5. If login fails, credentials are retried automatically

**Setup:**
1. Open **Settings → File Hosts → Rapidgator**
2. Enter credentials as: `username:password`
3. Click **Test Connection**
4. imxup logs in and caches the token

---

### 4. Session-Based Cookies

**Hosts:** Filedot (filedot.to), Filespace (filespace.com)

**What it is:** Username/password for session-based login with optional CAPTCHA.

**Storage:** OS Keyring (credentials) + Cookie cache
- **Used for:** Creating upload sessions
- **Format:** `username:password`
- **Session Expiry:** 1 hour (auto-refresh on next upload)
- **CAPTCHA:** Filedot uses visual CAPTCHA (solved automatically by imxup)

**Setup:**
1. Open **Settings → File Hosts → [Host]**
2. Enter credentials as: `username:password`
3. Click **Test Connection**
4. If CAPTCHA required (Filedot), imxup solves it automatically
5. Session cookies are cached for future uploads

---

## Storage Methods

IMXuploader uses a two-tier storage system to maximize both security and compatibility.

### Method 1: OS Keyring (Preferred)

**Supported Platforms:**
- **Windows:** Credential Manager (built-in)
- **macOS:** Keychain (built-in)
- **Linux:** Secret Service / GNOME Keyring (install `python3-keyring`)

**Security:** Credentials stored in OS-protected vault with user authentication
- Windows: Windows Credential Manager encryption
- macOS: Keychain encryption with system password
- Linux: Secret Service daemon encryption

**Advantages:**
- Most secure (OS-level encryption)
- Zero plaintext exposure
- Automatic cleanup on logout (Windows)
- Integration with system password manager

**How to verify OS Keyring is working:**
```bash
# Windows - Open Credential Manager
Control.exe /name Microsoft.CredentialManager

# Linux - Check Secret Service daemon
systemctl --user status secrets-tool

# macOS - Keychain Access app
open /Applications/Utilities/Keychain\ Access.app
```

If OS keyring unavailable, imxup automatically falls back to encrypted storage.

---

### Method 2: Encrypted Fallback (Fernet)

**Location:** `~/.imxup/config.ini` (encrypted sections only)

**Encryption:** Fernet (AES-128 in CBC mode)
- **Key:** Derived from PBKDF2-HMAC-SHA256 (100,000 iterations)
- **Format:** Encrypted binary blob (not readable as plaintext)

**When it's used:**
- OS Keyring unavailable or broken
- System doesn't support keyring access
- Development/testing environments

**File Structure:**
```ini
[credentials]
imxto_username = <encrypted>
imxto_password = <encrypted>
rapidgator_creds = <encrypted>
fileboom_api_key = <encrypted>
```

**Decryption is automatic:**
- On application startup, imxup attempts OS Keyring first
- If unavailable, automatically uses encrypted config file
- User never interacts with decryption—it's transparent

**Security Note:** The encrypted file is still more secure than plaintext, but OS Keyring is strongly preferred for production use.

---

## Setting Up Credentials

### Step 1: Open Settings

**Via Menu:** File → Settings
**Via Keyboard:** Ctrl+,

### Step 2: Navigate to Credential Sections

#### IMX.to Setup
1. Click **General** tab
2. Enter IMX.to username and password
3. Click **Test Connection** button
4. Wait for "Connection successful" message

#### File Host Setup
1. Click **File Hosts** tab
2. Select a host from the dropdown (e.g., "Rapidgator")
3. Enable the host with the checkbox
4. Enter credentials:
   - **API Key hosts** (Fileboom, Keep2Share, Tezfiles, Katfile): Paste API key
   - **Token Login** (Rapidgator): Enter `username:password`
   - **Session-Based** (Filedot, Filespace): Enter `username:password`
5. Click **Test Connection**

### Step 3: Test Connection

The test connection button verifies your credentials before saving:

**What it does:**
1. Attempts authentication with the file host
2. Retrieves account information (storage quota, premium status, email)
3. Deletes test file (if host supports deletion)
4. Displays account details and status

**Success message:**
```
Connection successful!
Account: user@example.com
Premium: Yes (expires 2025-12-31)
Storage: 245.8 GB / 1000 GB
```

**Error handling:**
- If test fails, error message explains why (invalid credentials, network error, etc.)
- Credentials are NOT saved if test fails
- You can try again with different credentials

### Step 4: Save and Done

After successful test, click **OK** or **Save** to store credentials:
- Saved to OS Keyring first
- Falls back to encrypted config if keyring unavailable
- Credentials persist across application restarts

---

## Security Notes

### What's Encrypted?

**All credentials are encrypted:**
- ✓ IMX.to username and password
- ✓ File host API keys
- ✓ Rapidgator username/password
- ✓ Filedot/Filespace username/password
- ✓ Session cookies (during storage)

**Note:** Credentials in RAM (during active upload) are decrypted for use, which is necessary for authentication.

### What's NOT Encrypted?

**Never stored by imxup:**
- ✗ Credentials sent to third-party servers (except the file host itself)
- ✗ Plaintext passwords on disk
- ✗ Credentials in log files or debug output
- ✗ Passwords in registry/plist (only in OS Keyring)

### Best Practices

1. **Use strong passwords** for all accounts
2. **API keys:** Treat like passwords—don't share or commit to version control
3. **Rapid Gator:** Use a unique password (not your main email password)
4. **Never disable OS Keyring** if available (encrypted fallback is less secure)
5. **Check account security** periodically:
   - Verify login from Settings → Test Connection
   - Check account access logs on file host websites

---

## Credential Recovery

### "Credentials Not Found" Error

**Cause:** OS Keyring unavailable or corrupted

**Solutions:**

**Windows:**
1. Open **Credential Manager** (Control.exe /name Microsoft.CredentialManager)
2. Look for "imxup" entries
3. If present, delete them
4. In imxup, re-enter credentials and test connection

**macOS:**
1. Open **Keychain Access** (Applications → Utilities)
2. Search for "imxup"
3. Delete any found entries
4. In imxup, re-enter credentials and test connection

**Linux:**
1. Restart Secret Service daemon:
   ```bash
   systemctl --user restart secrets-tool
   ```
2. Or use encrypted config fallback (no action needed)

### Password Change

If you change your password on a file host:

1. **Rapidgator / Session-based hosts:**
   - Open imxup Settings
   - Re-enter new credentials
   - Click Test Connection
   - Old token cache automatically invalidated

2. **API Key hosts:**
   - Generate new API key on host website
   - Open imxup Settings
   - Replace old API key with new one
   - Click Test Connection

3. **IMX.to:**
   - Open imxup Settings → General
   - Enter new password
   - Click Test Connection

### Forgotten Password

**If you forgot your file host password:**

1. Use "Forgot Password" on the file host website
2. Reset your password
3. In imxup, update the password in Settings
4. Test the connection

**If you forgot IMX.to password:**

1. Visit imx.to website
2. Use "Forgot Password" to reset
3. In imxup Settings → General, enter new password
4. Test the connection

### Reset All Credentials

**Warning:** This deletes all stored credentials from imxup (not from your accounts)

1. Open **Settings → Advanced**
2. Click **Clear All Credentials**
3. Confirm when prompted
4. Re-enter all credentials from scratch

---

## Troubleshooting

### Test Connection Fails

**Error: "Connection refused"**
- Check internet connection
- Verify file host is online (visit website)
- Try again in a few seconds

**Error: "Invalid credentials"**
- Verify username/password or API key is correct
- Check for typos (especially spaces)
- Copy-paste from another source to avoid typos
- Generate new API key if old one expired

**Error: "Network timeout"**
- Slow internet connection
- Try again (may be temporary)
- Check firewall/antivirus not blocking uploads

### Credentials Lost After Restart

**Cause:** Credentials not saved to OS Keyring

**Solution:**
1. Check if encrypted fallback exists: `~/.imxup/config.ini`
2. If not, OS Keyring wasn't available when saving
3. Re-enter credentials and ensure test passes
4. Check OS Keyring availability:
   - Windows: Control.exe /name Microsoft.CredentialManager
   - Linux: `sudo apt-get install python3-keyring`
   - macOS: Keychain should always be available

### Multiple Credentials Not Working

**If some file hosts work but others don't:**

1. Test each host individually in Settings
2. If one fails, that host has the problem credential
3. Delete and re-enter just that host's credential
4. Test again

### Token Refresh Failures

**For Rapidgator token:**

**Error: "Token expired, please re-login"**
1. Open Settings → File Hosts → Rapidgator
2. Enter username:password again
3. Click Test Connection (this forces new token)
4. Try upload again

**Why tokens fail:**
- Session idle too long (24-hour limit)
- Too many concurrent uploads (rate limit)
- Network interruption during token use

### CAPTCHA Solving Failed (Filedot)

**Error: "Failed to solve CAPTCHA"**

**Solutions:**
1. Check internet connection (needed to fetch CAPTCHA image)
2. Try again (sometimes CAPTCHA images fail to load)
3. Temporarily disable Filedot in Settings
4. Try another file host

---

## See Also

- [File Host Upload Guide](./multi-host-upload.md) — Detailed setup for each file host
- [Setup Instructions](../getting-started/setup.md) — Initial application setup
- [Settings Reference](../reference/FEATURES.md) — All configuration options
- [Troubleshooting](../troubleshooting/troubleshooting.md) — Common issues and solutions

---

**Version:** 0.6.16
**Last Updated:** 2026-01-03
