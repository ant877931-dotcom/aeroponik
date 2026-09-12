# 🌿 Pakcoy Plant Health Detection API

A production-ready **FastAPI** backend serving a custom **YOLOv8** model for detecting plant diseases in Pakcoy. Designed for native (no-Docker) cloud deployment on **Render** or **Railway**, and built to integrate with an ESP32 camera + Vercel-hosted web dashboard.

---

## 📁 Project Structure

```
yolo-api/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, CORS, /deteksi endpoint
│   ├── inference.py     # Thread-safe async YOLOv8 engine
│   └── validation.py    # Input sanitisation & anti-mimicry guards
├── models/
│   └── best.pt          # ← Place your model file here
├── requirements.txt     # Pinned, PaaS-compatible dependencies
├── Procfile             # Start command for Render / Railway / Heroku
├── runtime.txt          # Python version pin
├── .env.example         # Environment variable template
└── README.md
```

---

## 🚀 Local Development

### 1. Place your model
```bash
cp /path/to/best.pt models/best.pt
```

### 2. Create & activate a virtual environment
```bash
python -m venv venv
# macOS / Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env and set ALLOWED_ORIGINS if needed
```

### 5. Start the server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Visit **`http://localhost:8000/docs`** for the interactive Swagger UI.

---

## ☁️ Deployment (No Docker)

### Render.com (Recommended)

1. Push this `yolo-api/` directory to a **GitHub repository**.
2. In Render → **New Web Service** → connect the repo.
3. Set:
   | Setting | Value |
   |---------|-------|
   | **Environment** | `Python 3` |
   | **Root Directory** | `yolo-api` *(if in a monorepo)* |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | *(auto-detected from `Procfile`)* |
4. Add **Environment Variables**:
   ```
   ALLOWED_ORIGINS=https://your-app.vercel.app
   ```
5. Upload `best.pt` via a [Render Disk](https://render.com/docs/disks) mounted at `/opt/render/project/src/models/`.

### Railway.app

1. Create a new project → **Deploy from GitHub Repo**.
2. In project settings → **Service** → **Start Command**:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --loop uvloop --http httptools
   ```
3. Set environment variables:
   ```
   ALLOWED_ORIGINS=https://your-app.vercel.app
   ```
4. Upload `best.pt` using Railway's volume or include it in the repo (if ≤ 100 MB).

---

## 📡 API Reference

### `GET /`
Root health check.

```json
{ "status": "ok", "service": "Pakcoy Plant Health Detection API", "version": "1.0.0" }
```

### `GET /health`
Model readiness check.

```json
{ "status": "healthy", "model_loaded": true }
```

Returns **503** if the model failed to load.

### `POST /deteksi`
Detect plant diseases from an uploaded image.

**Request** — `multipart/form-data`:

| Field | Type | Notes |
|-------|------|-------|
| `file` | binary | JPEG, PNG, BMP, WEBP, TIFF — max 20 MB |

**Response**:
```json
{
  "status": "success",
  "detected_classes": ["Bercak Daun", "Sehat"],
  "detections": [
    { "label": "Sehat",       "confidence": 0.912 },
    { "label": "Bercak Daun", "confidence": 0.784 }
  ],
  "count": 2,
  "inference_time_ms": 143.7
}
```

---

## 🔗 Frontend Integration (Vercel / ESP32 Dashboard)

```javascript
// app.js — calling the API from your Vercel frontend
async function detectDisease(imageFile) {
  const formData = new FormData();
  formData.append("file", imageFile);

  const response = await fetch("https://your-api.onrender.com/deteksi", {
    method: "POST",
    body: formData,
    // Do NOT set Content-Type manually — the browser handles multipart boundaries
  });

  if (!response.ok) {
    const err = await response.json();
    throw new Error(err.detail || "Detection failed");
  }

  const data = await response.json();
  console.log("Detected classes:", data.detected_classes);
  return data;
}
```

---

## 🔒 Security Architecture

| Layer | Mechanism | Protects Against |
|-------|-----------|-----------------|
| Extension whitelist | `validation.py` | Obvious non-image uploads |
| Magic-byte check | `validation.py` | Renamed file mimicry attacks |
| Pillow re-encode | `validation.py` | Polyglot payloads, EXIF exploits |
| Size cap (20 MB) | `validation.py` | Memory-exhaustion DoS |
| CORS origin lock | `main.py` + env var | Cross-origin request forgery |
| Single worker | `Procfile` | Model state corruption |

---

## 🧵 Concurrency Model

```
HTTP Request 1 ──┐
HTTP Request 2 ──┤─→ asyncio event loop (non-blocking)
HTTP Request 3 ──┘        │
                           ↓
              await loop.run_in_executor(executor, ...)
                           │
              ┌────────────┘
              ↓
   ThreadPoolExecutor (MAX_WORKERS=1)
              │
              ↓ threading.Lock acquired
   _blocking_inference()  ← PyTorch forward pass
              │
              ↓ Lock released
   Return detections → event loop → HTTP Response
```

The event loop is **never blocked** during inference. New requests are accepted and queued while inference runs in the background thread.

---

## ⚙️ GPU Upgrade

To enable CUDA acceleration on a GPU-enabled host, edit `requirements.txt`:

```diff
-torch==2.4.1
-torchvision==0.19.1
+torch==2.4.1+cu121
+torchvision==0.19.1+cu121
```

Add to the top of `requirements.txt`:
```
--extra-index-url https://download.pytorch.org/whl/cu121
```

Then increase `MAX_WORKERS` in `inference.py` to match your GPU count.
