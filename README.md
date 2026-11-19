# Campus OD – Smart On-Duty Management System

**Sri Krishna Arts and Science College (SKASC)**

A dedicated institutional platform for managing and verifying student On-Duty (OD) applications, workflows, and approvals across students, tutors, and administrators.

---

## Technology Stack

- **Frontend:** React 18, Vite, Tailwind CSS, Lucide React
- **Backend:** Python 3.13, FastAPI, Uvicorn, Pydantic Settings
- **Database:** PostgreSQL (Architecture prepared), SQLAlchemy 2.0, Alembic
- **Storage:** Private local storage directory (`backend/storage`)
- **DevOps:** Git, Docker, Nginx, GitHub Actions (to be configured in upcoming phases)

---

## Directory Structure

```text
CAMPUS OD/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── layout/       # Institutional Header, Footer
│   │   │   └── ui/           # Reusable UI primitives (Card, Badge)
│   │   ├── App.jsx           # Starter institutional page & health monitor
│   │   ├── index.css         # Tailwind directives & institutional styling
│   │   └── main.jsx          # React DOM entrypoint
│   ├── index.html
│   ├── package.json
│   ├── postcss.config.js
│   ├── tailwind.config.js    # SKASC Navy theme tokens
│   ├── vite.config.js
│   └── .env.example
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/           # API v1 routes
│   │   ├── core/             # Application settings & environment config
│   │   ├── database/         # SQLAlchemy 2.0 Base & session dependency
│   │   ├── dependencies/     # Request-scoped dependencies
│   │   ├── models/           # SQLAlchemy ORM models (Phase 2)
│   │   ├── schemas/          # Pydantic schemas (Phase 2)
│   │   ├── services/         # Business logic layer
│   │   └── main.py           # FastAPI entrypoint, CORS, and health endpoint
│   ├── storage/              # Local private file storage (.gitkeep)
│   ├── tests/                # Unit and integration test suite
│   ├── requirements.txt
│   └── .env.example
├── docs/
│   └── PROJECT_STATUS.md     # Phase tracking and roadmap documentation
├── .gitignore                # Root Git ignore rules
└── README.md
```

---

## Getting Started

For the isolated authentication demo, see the [local demo guide](docs/LOCAL_DEMO.md). It covers reference data, explicit administrator bootstrap, invitation handoff, and the browser flow.

### Prerequisites
- Node.js (v18+) and npm
- Python (v3.11+ / v3.13)
- Git

### 1. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The frontend will start at `http://localhost:5173`.

To verify the production build:
```bash
npm run build
```

### 2. Backend Setup
```bash
cd backend
# Create virtual environment using your Python executable
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start development server
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
The backend API documentation will be available at:
- Root Health Check: `http://localhost:8000/`
- Interactive Swagger UI: `http://localhost:8000/docs`
- Alternative ReDoc: `http://localhost:8000/redoc`

---

## Current Status (Phase 1)
- [x] Monorepo workspace structure initialized
- [x] Git repository initialized with strict exclusion rules
- [x] React + Vite + Tailwind CSS foundation established with SKASC Navy theme
- [x] FastAPI backend foundation with root health check (`GET /`) and CORS
- [x] Modular architecture separating config, database layer, routes, and storage
- [ ] Phase 2: PostgreSQL schema design and SQLAlchemy 2.0 models (Upcoming)
