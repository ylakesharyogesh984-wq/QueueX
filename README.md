# QueueX – Smart Virtual Queue Management System
### Exclusively Built for CGC University, Mohali, Punjab, India

QueueX is a modern virtual queue management platform tailored for CGC University. It digitizes physical lines across college administrative counters, libraries, accounts, examination branches, and placement cells, eliminating long standing queues.

---

## 🌟 Key Features

### 1. Student Portal
- **Virtual Token Generation**: Instant token generation for university counters with service reason selection.
- **Real-Time Status & QR Code**: Live queue position tracking, estimated waiting time, and unique scannable verification QR code.
- **Instant Cancellation & Duplicate Prevention**: Prevents duplicate active tokens and allows self-service cancellation.
- **Live Notifications**: Automated alerts when it's your turn to proceed to the desk.
- **Profile & Settings**: View enrolled department details and reset security credentials.

### 2. Operator Portal
- **Counter Desk Dashboard**: Real-time stats on waiting students, tokens served today, and average service time.
- **Action Suite**:
  - `CALL NEXT`: Calls the next waiting student in strict FIFO order.
  - `COMPLETE`: Marks the current service finished and notifies the student.
  - `SKIP`: Flags no-show students.
  - `RECALL`: Calls back previously skipped students.
  - `PAUSE / RESUME`: Manages temporary queue pauses.
  - `OPEN / CLOSE`: Toggles desk availability.
- **Searchable Queue Table**: Fast live filtering by token number, student name, and roll number.

### 3. Central Administration Console
- **Central Analytics Dashboard**: Real-time traffic, counter statuses, and 7-day token volume visualizer via Chart.js.
- **Department Management**: Add, edit, and toggle campus departments (Accounts, Registrar, Library, Examination, CRC, Hostel).
- **Counter Window Management**: Provision counters, set service benchmarks, and assign operator desks.
- **Operator Staffing**: Create operator logins and bind staff to counter windows.
- **Daily Audit & CSV Reports**: Filter token logs by date and department with instant CSV export.

### 4. Concurrency & Security
- **Thread-Safe Queue Mutex**: Prevents race conditions during simultaneous token generation or desk calls.
- **Strict Anti-IDOR**: Guarantees tokens cannot be cancelled or altered by unauthorized users.
- **PostgreSQL & SQLite Dual Engine**: Native support for SQLite locally and PostgreSQL on Render / Railway.
- **WebSocket Live Updates**: Fast socket room broadcasts with fallback 5-second polling.

---

## 🎨 Design System
- **Neumorphism + High-Tech SaaS**: Soft ambient shadows, inset embossed controls, CGC Blue `#0f2b48` & `#1d4ed8` accents.
- **Light & Dark Themes**: Fully switchable theme toggle with persistent local preference.
- **Mobile Responsive**: Adaptive navigation bar, touch-friendly desk buttons, and responsive grid tables.

---

## 🚀 Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run with startup script or python
./start.sh
# or
python app.py
```
Visit `http://localhost:5000` in your web browser.

### Default Demo Credentials:
- **Student**: `student@cgc.edu.in` / `Student@QueueX2026` (Roll: `2201045`)
- **Operator**: `operator@cgc.edu.in` / `Operator@QueueX2026` (Counter: Accounts W1)
- **Admin**: `admin@cgc.edu.in` / `Admin@QueueX2026` (Admin Block Room 101)

---

## 🌐 Production Deployment (Render)

1. Create a **Web Service** connected to this repository.
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `gunicorn --worker-class gthread --workers 1 --threads 20 --bind 0.0.0.0:$PORT app:app`
4. Set Environment Variables:
   - `SECRET_KEY`: `<secure-random-key>`
   - `DATABASE_URL`: `postgresql://...` (Render PostgreSQL connection string)
   - `SESSION_COOKIE_SECURE`: `1`
5. **Health Check Path**: `/health`

## 🌐 Production Deployment (Render / Railway)

1. **Build Command**: `pip install -r requirements.txt`
2. **Start Command**: `gunicorn --worker-class gthread --workers 1 --threads 20 --bind 0.0.0.0:$PORT app:app`
3. **Database**: Attach PostgreSQL and configure the `DATABASE_URL` environment variable. (If `DATABASE_URL` is omitted, local SQLite storage is used).
4. **Health Check Path**: `/health` (Returns HTTP 200 `{"status": "healthy", "app": "CampusOne"}`)
