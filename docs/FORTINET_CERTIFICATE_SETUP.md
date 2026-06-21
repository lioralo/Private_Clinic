# Fortinet Network Certificate Setup Guide

## Problem
Users behind Fortinet firewalls see: `net::ERR_CERT_AUTHORITY_INVALID` ("Fortinet wasn't installed properly")

This is **network-level TLS inspection**, not a server issue.

## Root Cause
Fortinet firewall intercepts HTTPS traffic and re-encrypts it with an enterprise CA certificate. Browsers don't trust this CA by default, causing certificate errors.

---

## Solution: Two Parts

### Part 1: Agent Deployment (Server-Side)
### Part 2: End-User Installation (Client-Side)

---

## **PART 1: AGENT DEPLOYMENT INSTRUCTIONS**

Run this on your AWS server during deployment:

```bash
# Set these in your deployment environment:
FORTINET_CA_CERT_PATH="${FORTINET_CA_CERT_PATH:-}"
DOMAIN="${DOMAIN}"
SSH_KEY_PATH="${SSH_KEY_PATH}"
SERVER_IP="${SERVER_IP}"

# If you have the Fortinet CA certificate (.pem or .crt file), provide the path:
# export FORTINET_CA_CERT_PATH="/path/to/fortinet-ca.pem"

ssh -i "$SSH_KEY_PATH" ubuntu@"$SERVER_IP" << 'DEPLOY_EOF'
set -euo pipefail

cd /opt/Private_Clinic

# Create directory for custom CA certificates
sudo mkdir -p /opt/Private_Clinic/certs

# If Fortinet CA was provided, copy it to the certs directory
if [ -n "${FORTINET_CA_CERT_PATH:-}" ] && [ -f "$FORTINET_CA_CERT_PATH" ]; then
  echo "Copying Fortinet CA certificate..."
  sudo cp "$FORTINET_CA_CERT_PATH" /opt/Private_Clinic/certs/fortinet-ca.pem
  sudo chmod 644 /opt/Private_Clinic/certs/fortinet-ca.pem
  echo "✓ Fortinet CA certificate installed"
else
  echo "⚠ No Fortinet CA certificate provided"
  echo "  To install later, copy the .pem file to: /opt/Private_Clinic/certs/fortinet-ca.pem"
fi

# Ensure Caddy can read certsdir
sudo chown -R 1000:1000 /opt/Private_Clinic/certs 2>/dev/null || true

# Restart Caddy to pick up any new certificates
sudo docker compose --env-file .env.prod -f docker-compose.prod.yml restart caddy

echo "✓ Certificate setup complete"
DEPLOY_EOF
```

### If Fortinet CA is Available

If you have the Fortinet root CA certificate (.pem or .crt file), run:

```bash
# Download or obtain the Fortinet CA certificate file and provide it:
FORTINET_CA_CERT_PATH="/path/to/fortinet-ca.pem"

# Then run the deployment script above with:
export FORTINET_CA_CERT_PATH
# ... run the ssh command
```

---

## **PART 2: END-USER INSTALLATION (For Your Clinic Users)**

Send these instructions to users behind Fortinet:

### **For Windows Users**

1. **Download the Fortinet CA certificate:**
   - Ask your IT department for the "Fortinet Root CA" certificate file (.pem, .cer, or .crt)
   - Save it to your Desktop

2. **Install in Windows Trust Store:**
   - Right-click the certificate file → "Install Certificate"
   - Select "Local Machine" (or "Current User" if you don't have admin)
   - Click "Next"
   - Choose "Place all certificates in the following store"
   - Click "Browse"
   - Select "Trusted Root Certification Authorities"
   - Click "OK" → "Finish"
   - Restart your browser (or entire system)

3. **Verify:**
   - Visit `https://<clinic-domain>`
   - The padlock should now show green ✓

---

### **For macOS Users**

1. **Download the Fortinet CA certificate from your IT:**
   - Get the certificate file (.pem or .crt)

2. **Install in Keychain:**
   ```bash
   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/Desktop/fortinet-ca.pem
   ```
   - Enter your Mac password when prompted

3. **Restart browser**

4. **Verify:**
   - Visit `https://<clinic-domain>`
   - Should show secure ✓

---

### **For Linux Users**

1. **Copy certificate to system store:**
   ```bash
   sudo cp fortinet-ca.pem /usr/local/share/ca-certificates/fortinet-ca.crt
   sudo update-ca-certificates
   ```

2. **For Chrome/Chromium specifically:**
   ```bash
   # If using chromium on Linux:
   chromium-browser --ssl-version-min=TLSv1 --disable-preconnect https://<clinic-domain>
   ```

3. **Verify:**
   - Visit `https://<clinic-domain>`
   - Check certificate issuer should show "Fortinet" now trusted

---

### **Alternative: Bypass for User (Not Recommended)**

If CA certificate is not available and user's network allows it:

#### **Chrome/Edge Users**
1. In URL bar, click the padlock icon with red X
2. Click "Certificate is not valid" → "Details"
3. Look for issuer (should say "Fortinet" or "proxy")
4. Note the issuer details
5. In address bar, type: `thisisunsafe` (don't press enter, just type while on the error page)
   - This temporarily bypasses the cert check

#### **Firefox Users**
1. At the NET::ERR page, click "Advanced"
2. Click "Accept the Risk and Continue"

⚠ **This works once per session and is not recommended for production use.**

---

## **Technical Summary for IT Department**

If your site is behind Fortinet and users report certificate errors:

1. **Fortinet is intercepting HTTPS (SSL Inspection enabled)**
   - This is expected enterprise security behavior

2. **Fix options:**
   - Option A: Install Fortinet root CA in client trust store (recommended)
   - Option B: Whitelist the domain in Fortinet to skip SSL inspection
   - Option C: Users use non-Fortinet network (cellular, VPN)

3. **Confirm cert is correct:**
   ```bash
   curl -Iv https://<clinic-domain> 2>&1 | grep -i issuer
   ```
   - If issuer shows "Fortinet" or "Proxy-CA": **Network interception is active** ← this is expected
   - If issuer shows "Let's Encrypt" or "ZeroSSL": **Direct access, no interception** ← server is correct

---

## Quick Reference: Obtain Fortinet CA Certificate

Ask your network/IT team for:
- "Fortinet Root CA certificate"
- Or: "Fortinet proxy CA"
- Or: "Company root certificate authority"

File formats they might provide: `.pem`, `.crt`, `.cer`, `.der`

If they provide `.der` format, convert it:
```bash
openssl x509 -inform DER -in certificate.der -out certificate.pem
```

---

## Testing Your Setup

After users install the CA:

1. **Clear browser cache:**
   - Chrome: Shift+Ctrl+Delete (Windows/Linux) or Cmd+Shift+Delete (Mac)

2. **Test the URL:**
   ```bash
   curl -Iv https://<clinic-domain>
   ```
   - Should show: `TLS version: TLSv1.3` (or 1.2) with no certificate errors
   - Issuer may show either "Let's Encrypt" (direct) or "Fortinet" (intercepted but trusted)

3. **In browser:**
   - Visit `https://<clinic-domain>`
   - Padlock should be green ✓
   - No "Not Secure" warning

---

## If Problem Persists

1. **User cleared browser cache?** → Yes, ask them to restart browser completely
2. **CA installed system-wide or browser-only?** → Some users need system store, others need browser store
3. **Is it the right Fortinet CA?** → Ask IT to verify they gave the root CA, not intermediate
4. **Wrong domain configured in Fortinet?** → Ask IT to whitelist `*.yourdomain.com` in Fortinet rules

Contact your IT department if the certificate error persists after installation.
