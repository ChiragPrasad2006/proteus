# Proteus — The Local-First AI Email Agent That Becomes You, Over Time

> **Proteus** is a local-first, privacy-preserving AI email agent that learns your personal writing style, manages multiple email accounts, and autonomously drafts, replies, and sends emails on your behalf — all running entirely on your hardware.

---

## 🏗️ Core Architecture Overview

Proteus implements a **4-Tier Hybrid Personalization Stack** that progressively refines its understanding of you:

### Tier 1 — Multi-Client Ingestion & Deterministic Stylometry
- **Gmail OAuth2** (`gmail.readonly` + `gmail.send`) via Google APIs
- **Outlook / Microsoft Graph** (`Mail.Read` + `Mail.Send`)
- **IMAP/SMTP** generic connectors for any provider
- **Local file ingestion** — `.mbox` and `.eml` drag-and-drop
- **Strict per-account isolation** — every message tagged with `X-Account-ID` for zero cross-contamination
- **Deterministic stylometry** — greeting, sign-off, sentence length, tone, vocabulary fingerprint extracted per account

### Tier 2 — Audience-Tagged & Time-Decayed RAG
- **CPU-hosted embeddings** — `sentence-transformers/all-MiniLM-L12-v2` (no GPU required for retrieval)
- **LanceDB** vector store with on-disk persistence
- **90-day half-life exponential recency decay** — recent emails weigh more, old context fades naturally
- **Audience topology matching** — `1on1_private` / `group_cc` / `broadcast_bcc` tags ensure replies match the right social context

### Tier 3 — Dual-Mode `Qwen3:8B` Engine (via Ollama)
| Mode | `think` | Use Case |
|------|---------|----------|
| **Fast Drafting** | `false` | Sub-second email generation with `To`/`Cc`/`Bcc` Audience Topology prompting |
| **Deep Reasoning** | `true` | Stylometry profiling, edit-diff analysis, multi-turn conversation synthesis |

### Tier 4 — Autonomous Dispatch & Self-Improving Loop
- **Natural-language persona resolution** — `"Email Manu and CC Jatin & Chiranth"` → resolves contacts, composes, queues
- **First-recipient safety gate** — every new contact defaults to `PENDING_REVIEW` before send
- **Atomic style rule extraction** — user edits to drafts are diffed and distilled into permanent style rules
- **Continuous learning** — every sent email reinforces the personalization loop

---

## 🎨 Frontend Studio (`frontend/`)
**Digital Naturalism & Brutalist Editorial UI**
- **Palette**: `#0C0A09` Stone Black, `#1C1917` Warm Charcoal, `#D4F268` Acid Lime
- **Typography**: `Newsreader` (editorial headlines) + `Instrument Sans` (UI)
- **1-click Google Sign-In onboarding** — OAuth flow completes in-browser
- **Multi-account LLM chat workspace** — chat with your email brain, switch accounts instantly
- **Real-time draft preview** — see the email as the model generates it

---

## 🚀 Quickstart

### Option A: One-Click Launcher — `Proteus.exe` (Recommended, Windows)
```powershell
# Clone the repo
git clone https://github.com/ChiragPrasad2006/proteus.git
cd proteus

# Double-click or run:
.\Proteus.exe
```
The launcher will:
1. ✅ Set `HF_HOME=D:\huggingface_cache` and `EMAIL_WRITER_LOCAL_DATA_DIR=./local_user_data`
2. ✅ Start Ollama (if not running) and pull `qwen3:8b`
3. ✅ Launch FastAPI backend on `http://127.0.0.1:8000`
4. ✅ Launch Vite frontend on `http://localhost:5173` and open your browser
5. ✅ Clean shutdown on close (Ctrl+C or close window)

> **No manual dependency management** — `Proteus.exe` is a standalone executable (~6 MB) built with PyInstaller.

---

### Option B: Manual Terminal Commands

#### Prerequisites
- **Ollama** installed and `qwen3:8b` pulled: `ollama pull qwen3:8b`
- **Python 3.10+** with venv at `D:\MLops\.venv` (or update `start_proteus.bat`)
- **Node.js 18+** and `npm`
- **Google Cloud Console** project with Gmail API enabled (for Gmail OAuth)

#### Terminal 1 — Ollama
```powershell
ollama serve
# In another terminal:
ollama pull qwen3:8b
```

#### Terminal 2 — FastAPI Backend
```powershell
cd proteus
$env:HF_HOME = "D:\huggingface_cache"
$env:EMAIL_WRITER_LOCAL_DATA_DIR = "$PWD\local_user_data"
D:\MLops\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
Verify: `curl http://127.0.0.1:8000/api/health` → `{"status":"ok"}`

#### Terminal 3 — Vite Frontend
```powershell
cd proteus\frontend
npm install        # first time only
npm run dev
```
Open `http://localhost:5173` in your browser.

---

## 🔐 Google OAuth Setup (Gmail Integration)

1. Go to **Google Cloud Console** → **APIs & Services** → **Credentials**
2. Create **OAuth 2.0 Client ID** → **Desktop application** (not Web)
3. **Authorized redirect URIs**: `http://localhost:8000/auth/google/callback`
4. Download `client_secret.json` → place in `proteus/` root (auto-gitignored)
5. In the Proteus UI: **Account Switcher → Add Account → Gmail** → upload `client_secret.json` → follow OAuth flow

> **Scopes requested**: `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.send`, `https://www.googleapis.com/auth/userinfo.email`, `openid`

> **Graceful handling**: If `client_secret.json` is missing, the UI shows an inline **1-Step Google OAuth Setup Modal** with a file-upload dropzone and step-by-step instructions to create a Desktop OAuth client ID in Google Cloud Console.

---

## 📡 REST API Reference

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/health` | Health check | None |
| `GET` | `/api/auth/google/status` | Check OAuth credentials status | None |
| `POST` | `/api/auth/google/upload-credentials` | Upload `client_secret.json` | None |
| `POST` | `/api/auth/google/start` | Initiate Gmail OAuth flow | None |
| `GET` | `/api/auth/google/callback` | OAuth callback (auto) | None |
| `GET` | `/api/accounts` | List connected email accounts | Cookie/Token |
| `POST` | `/api/accounts/switch` | Switch active account | Cookie/Token |
| `DELETE` | `/api/accounts/{account_id}` | Disconnect account | Cookie/Token |
| `GET` | `/api/emails` | List emails (paginated, filterable) | Cookie/Token |
| `POST` | `/api/emails/sync` | Trigger full sync for account | Cookie/Token |
| `POST` | `/api/draft` | Generate draft from intent + context | Cookie/Token |
| `POST` | `/api/draft/refine` | Refine draft with user feedback | Cookie/Token |
| `POST` | `/api/send` | Send email (respects PENDING_REVIEW gate) | Cookie/Token |
| `GET` | `/api/style/profile` | Get learned style profile for account | Cookie/Token |
| `POST` | `/api/style/learn` | Extract style rules from edit diff | Cookie/Token |
| `WS` | `/ws/chat` | Multi-account LLM chat workspace | Cookie/Token |

### Draft Generation Payload
```json
POST /api/draft
{
  "account_id": "gmail_primary",
  "intent": "Follow up on Q1 budget approval, request sign-off by Friday",
  "audience": "1on1_private",
  "to": ["manu@example.com"],
  "cc": ["jatin@example.com"],
  "bcc": [],
  "thread_id": "optional_thread_id_for_reply",
  "think_mode": false
}
```

### Send Payload (with safety gate)
```json
POST /api/send
{
  "draft_id": "uuid",
  "confirm_send": true,
  "bypass_review": false
}
```
- If recipient is **new** (no prior sent email), `bypass_review=false` → status = `PENDING_REVIEW`
- Review in UI → **Approve** → actually sends

---

## 🧪 Testing

```powershell
# Backend tests (pytest)
cd proteus
D:\MLops\.venv\Scripts\python.exe -m pytest tests/ -q

# Frontend type-check & build
cd proteus\frontend
npm run lint
npm run build
```

---

## 📁 Project Structure

```
proteus/
├── Proteus.exe                 # Standalone Windows launcher (~6 MB)
├── launcher.py                 # Source for Proteus.exe
├── .gitignore                  # Hardened: no secrets, no binaries, no caches
├── README.md                   # This file
├── LICENSE
├── requirements.txt            # Python dependencies
├── backend/
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # Central config (env-driven)
│   ├── automation/             # Tier 4: dispatch, style learning
│   ├── connectors/             # Tier 1: Gmail, Outlook, IMAP, MBOX
│   ├── generation/             # Tier 3: Qwen3:8B drafter (think=true/false)
│   ├── processing/             # Tier 1: cleaner, stylometry
│   ├── profiler/               # Tier 3: deep reasoning profiler
│   ├── retrieval/              # Tier 2: embedder, LanceDB vector store
│   ├── schemas.py              # Pydantic models (API contracts)
│   └── storage/                # Profile store, chat sessions, account manager
├── frontend/                   # Vite + React + TypeScript + Tailwind
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── tests/
│   ├── test_proteus_accounts.py
│   ├── test_proteus_chat.py
│   └── test_security_audit.py
├── local_user_data/            # GITIGNORED — per-account SQLite, tokens, style DB
├── oauth_tokens/               # GITIGNORED — OAuth refresh tokens
├── checkpoints/                # GITIGNORED — LoRA adapters, model checkpoints
└── exported_models/            # GITIGNORED — merged GGUF/ONNX exports
```

---

## ⚙️ Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `HF_HOME` | `~/.cache/huggingface` | Hugging Face cache (set to `D:\huggingface_cache` in launcher) |
| `EMAIL_WRITER_LOCAL_DATA_DIR` | `./local_user_data` | Per-account databases, tokens, style profiles |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_MODEL` | `qwen3:8b` | Model tag for drafting/profiling |
| `BACKEND_HOST` | `127.0.0.1` | FastAPI bind address |
| `BACKEND_PORT` | `8000` | FastAPI port |
| `FRONTEND_PORT` | `5173` | Vite dev server port |
| `LANCEDB_PATH` | `$EMAIL_WRITER_LOCAL_DATA_DIR/lancedb` | Vector store location |
| `SQLITE_PATH` | `$EMAIL_WRITER_LOCAL_DATA_DIR/proteus.sqlite3` | Relational store |

---

## 🛡️ Security & Privacy

- **100% local execution** — no data leaves your machine unless you explicitly send an email
- **OAuth tokens encrypted at rest** — stored in `local_user_data/` with per-account isolation
- **No telemetry, no analytics, no external logging**
- **Gitignore hardened** — `client_secret*.json`, `credentials.json`, `*.sqlite3`, `*.db`, `checkpoints/`, `exported_models/`, `local_user_data/`, `oauth_tokens/`, `frontend/node_modules/`, `frontend/dist/` all excluded
- **Security audit test** — `tests/test_security_audit.py` validates zero secrets in tracked files

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- **Qwen Team** — `Qwen3:8B` via Ollama
- **LanceDB** — embedded vector database
- **Sentence Transformers** — `all-MiniLM-L12-v2` embeddings
- **FastAPI + Vite + React + Tailwind** — the stack that makes it feel native
