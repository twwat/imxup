# Check if profile exists
Test-Path $PROFILE

# If it doesn't exist, create it
if (!(Test-Path $PROFILE)) {
    New-Item -Type File -Path $PROFILE -Force
}

# Add the encoding line to your profile
Add-Content $PROFILE "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8"
