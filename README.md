# QueueX

QueueX is a flask Flask + Socket.IO campus queue system. Students can generate a token for a counter, operators can call or skip tokens, and admins can view live analytics.

It is now also a Progressive Web App (PWA), so it can be installed on Android from Chrome and can be wrapped into an APK.

## Quick Start

Start QueueX in the background:
```bash
./start.sh
```

Stop QueueX:
```bash
./stop.sh
```

View live logs:
```bash
tail -f queuex.log
```

Open `http://127.0.0.1:5000`.

## Manual Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Demo Logins

Operator:

```text
username: operator
password: operator123
```

Admin:

```text
username: superadmin
password: super123
```

## Environment Variables

Use these before running the app when deploying or sharing outside a demo machine:

```bash
export SECRET_KEY="change-this-to-a-long-random-value"
export OPERATOR_USERNAME="operator"
export OPERATOR_PASSWORD="strong-password"
export ADMIN_USERNAME="superadmin"
export ADMIN_PASSWORD="strong-admin-password"
export QUEUEX_DB="database.db"
export FLASK_DEBUG="0"
export PORT="5000"
```

## Tests

```bash
python -m unittest
```

## Free APK Options

### Option 1: Free Install Without APK

This is the easiest path for college/demo use.

1. Deploy QueueX online with HTTPS.
2. Open the site in Android Chrome.
3. Tap Chrome menu.
4. Tap `Add to Home screen` or `Install app`.

QueueX will open like a normal mobile app with its own icon.

### Option 2: Free APK With Android Studio WebView

1. Install Android Studio.
2. Create `Empty Views Activity`.
3. Add Internet permission in `AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
```

4. Use a WebView in `MainActivity` and load your deployed QueueX URL.
5. Build APK from `Build > Generate Signed Bundle / APK`.

Important: do not use `127.0.0.1` inside APK. Deploy QueueX first and use that public HTTPS URL.

### Option 3: Free APK From PWA

Use Bubblewrap or PWABuilder after deployment:

1. Deploy QueueX on HTTPS.
2. Confirm `/static/manifest.json` works.
3. Confirm `/sw.js` works.
4. Generate Android package from the PWA.
5. Build signed APK/AAB.
