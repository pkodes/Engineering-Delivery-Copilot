"""
Deterministic code generators: AppSpec -> {relative_path: file_content}.

Design: the generated backend is *data-driven* — it reads `spec.json` at runtime,
so db/repository/seed/main are static, correct-by-construction files. Only the
per-entity routers and Pydantic schemas are generated. This keeps the surface for
generation bugs tiny while still emitting real, readable, per-domain code.
"""
from __future__ import annotations

import json

from .app_spec import AppSpec, Entity

# --------------------------------------------------------------------------- #
# Static backend files (data-driven, so no interpolation needed)
# --------------------------------------------------------------------------- #
_DB_PY = '''import json
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SPEC_PATH = BASE_DIR / "spec.json"
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR.parent / "app.db"))

with open(SPEC_PATH, "r", encoding="utf-8") as _f:
    SPEC = json.load(_f)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create a table for every entity in the spec (idempotent)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        for entity in SPEC["entities"]:
            columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
            for field in entity["fields"]:
                columns.append('"' + field["name"] + '" ' + field["sql_type"])
            cur.execute(
                'CREATE TABLE IF NOT EXISTS "' + entity["table"] + '" ('
                + ", ".join(columns) + ")"
            )
        conn.commit()
    finally:
        conn.close()
'''

_REPOSITORY_PY = '''from typing import Any, Optional

from .db import get_connection


class Repository:
    """Generic SQLite-backed CRUD repository for a single table."""

    def __init__(self, table: str, columns: list[str]) -> None:
        self.table = table
        self.columns = columns

    def list(self) -> list[dict[str, Any]]:
        conn = get_connection()
        try:
            rows = conn.execute(
                'SELECT * FROM "' + self.table + '" ORDER BY id DESC'
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get(self, item_id: int) -> Optional[dict[str, Any]]:
        conn = get_connection()
        try:
            row = conn.execute(
                'SELECT * FROM "' + self.table + '" WHERE id = ?', (item_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def count(self) -> int:
        conn = get_connection()
        try:
            row = conn.execute(
                'SELECT COUNT(*) AS n FROM "' + self.table + '"'
            ).fetchone()
            return int(row["n"]) if row else 0
        finally:
            conn.close()

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        cols = [c for c in self.columns if c in data]
        conn = get_connection()
        try:
            if cols:
                placeholders = ", ".join("?" for _ in cols)
                names = ", ".join('"' + c + '"' for c in cols)
                cur = conn.execute(
                    'INSERT INTO "' + self.table + '" (' + names + ") VALUES ("
                    + placeholders + ")",
                    [data[c] for c in cols],
                )
            else:
                cur = conn.execute('INSERT INTO "' + self.table + '" DEFAULT VALUES')
            conn.commit()
            new_id = cur.lastrowid
        finally:
            conn.close()
        return self.get(int(new_id))  # type: ignore[return-value]

    def update(self, item_id: int, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        if self.get(item_id) is None:
            return None
        cols = [c for c in self.columns if c in data]
        if cols:
            assignments = ", ".join('"' + c + '" = ?' for c in cols)
            conn = get_connection()
            try:
                conn.execute(
                    'UPDATE "' + self.table + '" SET ' + assignments + " WHERE id = ?",
                    [data[c] for c in cols] + [item_id],
                )
                conn.commit()
            finally:
                conn.close()
        return self.get(item_id)

    def delete(self, item_id: int) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                'DELETE FROM "' + self.table + '" WHERE id = ?', (item_id,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
'''

_SEED_PY = '''from .db import SPEC
from .repository import Repository


def seed_all() -> None:
    """Insert seed rows for any entity whose table is currently empty."""
    for entity in SPEC["entities"]:
        repo = Repository(entity["table"], [f["name"] for f in entity["fields"]])
        if repo.count() > 0:
            continue
        for row in entity.get("seed", []):
            try:
                repo.create(row)
            except Exception:
                # A malformed seed row must never crash startup.
                pass
'''

_MAIN_PY = '''from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .db import SPEC, init_db
from .routers import all_routers
from .seed import seed_all

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_all()
    yield


app = FastAPI(title=SPEC["app_title"], version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "app": SPEC["app_title"]}


@app.get("/api/_meta")
def meta():
    return {
        "app_title": SPEC["app_title"],
        "description": SPEC["description"],
        "primary_color": SPEC["primary_color"],
        "entities": [
            {
                "name": e["name"],
                "name_plural": e["name_plural"],
                "table": e["table"],
                "path": e["path"],
                "fields": e["fields"],
            }
            for e in SPEC["entities"]
        ],
    }


for _router in all_routers:
    app.include_router(_router)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
'''

_REQUIREMENTS = "fastapi==0.115.6\nuvicorn[standard]==0.32.1\n"

_BACKEND_DOCKERFILE = '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
'''

_BACKEND_DOCKERIGNORE = "__pycache__/\n*.db\n.venv/\n"


# --------------------------------------------------------------------------- #
# Dynamic backend files (per-entity)
# --------------------------------------------------------------------------- #
def _schemas_py(spec: AppSpec) -> str:
    out = ["from typing import Optional", "", "from pydantic import BaseModel", "", ""]
    for e in spec.entities:
        out.append(f"class {e.name}Create(BaseModel):")
        for f in e.fields:
            if f.required:
                out.append(f"    {f.name}: {f.py_type}")
            else:
                out.append(f"    {f.name}: Optional[{f.py_type}] = None")
        out.append("")
        out.append("")
        out.append(f"class {e.name}Read({e.name}Create):")
        out.append("    id: int")
        out.append("")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _router_py(e: Entity) -> str:
    cols = ", ".join(repr(f.name) for f in e.fields)
    return f'''from fastapi import APIRouter, HTTPException

from ..repository import Repository
from ..schemas import {e.name}Create, {e.name}Read

router = APIRouter(prefix="/api/{e.table}", tags=["{e.name}"])
_repo = Repository("{e.table}", [{cols}])


@router.get("", response_model=list[{e.name}Read])
def list_{e.table}():
    return _repo.list()


@router.post("", response_model={e.name}Read, status_code=201)
def create_{e.var}(payload: {e.name}Create):
    return _repo.create(payload.model_dump(exclude_unset=True))


@router.get("/{{item_id}}", response_model={e.name}Read)
def get_{e.var}(item_id: int):
    item = _repo.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="{e.name} not found")
    return item


@router.put("/{{item_id}}", response_model={e.name}Read)
def update_{e.var}(item_id: int, payload: {e.name}Create):
    item = _repo.update(item_id, payload.model_dump(exclude_unset=True))
    if item is None:
        raise HTTPException(status_code=404, detail="{e.name} not found")
    return item


@router.delete("/{{item_id}}")
def delete_{e.var}(item_id: int):
    if not _repo.delete(item_id):
        raise HTTPException(status_code=404, detail="{e.name} not found")
    return {{"deleted": item_id}}
'''


def _routers_init_py(spec: AppSpec) -> str:
    imports = "\n".join(f"from . import {e.table}" for e in spec.entities)
    listing = ", ".join(f"{e.table}.router" for e in spec.entities)
    return f"{imports}\n\nall_routers = [{listing}]\n"


def _spec_json(spec: AppSpec) -> str:
    payload = {
        "app_title": spec.app_title,
        "description": spec.description,
        "slug": spec.slug,
        "primary_color": spec.primary_color,
        "entities": [
            {
                "name": e.name,
                "name_plural": e.name_plural,
                "table": e.table,
                "path": e.path,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "type": f.type,
                        "required": f.required,
                        "sql_type": f.sqlite_type,
                    }
                    for f in e.fields
                ],
                "seed": e.seed,
            }
            for e in spec.entities
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


# --------------------------------------------------------------------------- #
# Embedded admin console (dependency-free vanilla JS — guaranteed preview)
# --------------------------------------------------------------------------- #
_STATIC_INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Loading…</title>
  <style>
    :root { --brand: #6d28d9; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
           background: #0b0f19; color: #e5e7eb; }
    header { padding: 24px 28px; border-bottom: 1px solid rgba(255,255,255,.08);
             background: linear-gradient(135deg, rgba(255,255,255,.03), transparent); }
    header h1 { margin: 0; font-size: 22px; }
    header p { margin: 6px 0 0; color: #9ca3af; font-size: 14px; }
    .wrap { max-width: 1000px; margin: 0 auto; padding: 24px 28px; }
    .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }
    .tab { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08);
           color: #cbd5e1; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 14px; }
    .tab.active { background: var(--brand); border-color: var(--brand); color: #fff; }
    .card { background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08);
            border-radius: 12px; padding: 18px; margin-bottom: 18px; }
    form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; align-items: end; }
    label { font-size: 12px; color: #9ca3af; display: block; margin-bottom: 4px; }
    input, select { width: 100%; padding: 8px 10px; border-radius: 8px; background: #0e1424;
            border: 1px solid rgba(255,255,255,.1); color: #e5e7eb; font-size: 14px; }
    button.add { background: var(--brand); color: #fff; border: none; padding: 9px 16px;
            border-radius: 8px; cursor: pointer; font-weight: 600; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,.06); }
    th { color: #9ca3af; font-weight: 600; }
    .del { background: transparent; border: 1px solid rgba(239,68,68,.4); color: #fca5a5;
           border-radius: 6px; padding: 4px 8px; cursor: pointer; font-size: 12px; }
    .muted { color: #6b7280; font-size: 13px; }
    .err { color: #fca5a5; font-size: 13px; margin-top: 8px; }
    .badge { font-size: 11px; color: #9ca3af; border: 1px solid rgba(255,255,255,.1);
             padding: 2px 8px; border-radius: 999px; }
  </style>
</head>
<body>
  <header>
    <h1 id="title">Loading…</h1>
    <p id="desc"></p>
  </header>
  <div class="wrap">
    <div class="tabs" id="tabs"></div>
    <div class="card" id="form-card"></div>
    <div class="card"><div id="table"></div></div>
  </div>
  <script>
    const api = (p, opts) => fetch(p, opts).then(r => { if (!r.ok) throw new Error(r.status); return r.status === 204 ? null : r.json(); });
    let META = null, ACTIVE = null;

    async function boot() {
      try {
        META = await api('/api/_meta');
      } catch (e) {
        document.getElementById('title').textContent = 'API unreachable';
        document.getElementById('desc').textContent = 'Could not load /api/_meta.';
        return;
      }
      document.documentElement.style.setProperty('--brand', META.primary_color || '#6d28d9');
      document.title = META.app_title;
      document.getElementById('title').textContent = META.app_title;
      document.getElementById('desc').textContent = META.description || '';
      ACTIVE = META.entities[0] ? META.entities[0].table : null;
      renderTabs();
      renderEntity();
    }

    function renderTabs() {
      const el = document.getElementById('tabs');
      el.innerHTML = '';
      META.entities.forEach(e => {
        const b = document.createElement('button');
        b.className = 'tab' + (e.table === ACTIVE ? ' active' : '');
        b.textContent = e.name_plural;
        b.onclick = () => { ACTIVE = e.table; renderTabs(); renderEntity(); };
        el.appendChild(b);
      });
    }

    function entity() { return META.entities.find(e => e.table === ACTIVE); }

    function inputFor(f) {
      if (f.type === 'boolean') return '<select name="' + f.name + '"><option value="">—</option><option value="true">true</option><option value="false">false</option></select>';
      const t = f.type === 'integer' || f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text';
      const step = f.type === 'number' ? ' step="any"' : '';
      return '<input name="' + f.name + '" type="' + t + '"' + step + (f.required ? ' required' : '') + ' />';
    }

    function renderEntity() {
      const e = entity();
      const fc = document.getElementById('form-card');
      if (!e) { fc.innerHTML = '<p class="muted">No entities.</p>'; document.getElementById('table').innerHTML = ''; return; }
      fc.innerHTML =
        '<form id="create-form">' +
        e.fields.map(f => '<div><label>' + f.label + (f.required ? ' *' : '') + '</label>' + inputFor(f) + '</div>').join('') +
        '<div><button class="add" type="submit">Add ' + e.name + '</button></div>' +
        '</form><div class="err" id="form-err"></div>';
      document.getElementById('create-form').onsubmit = onCreate;
      loadRows();
    }

    function coerce(type, v) {
      if (v === '' || v == null) return undefined;
      if (type === 'integer') return parseInt(v, 10);
      if (type === 'number') return parseFloat(v);
      if (type === 'boolean') return v === 'true';
      return v;
    }

    async function onCreate(ev) {
      ev.preventDefault();
      const e = entity(), form = ev.target, body = {};
      e.fields.forEach(f => { const val = coerce(f.type, form.elements[f.name].value); if (val !== undefined) body[f.name] = val; });
      try {
        await api('/api/' + e.table, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        form.reset();
        document.getElementById('form-err').textContent = '';
        loadRows();
      } catch (err) {
        document.getElementById('form-err').textContent = 'Create failed (check required fields).';
      }
    }

    async function onDelete(id) {
      const e = entity();
      try { await api('/api/' + e.table + '/' + id, { method: 'DELETE' }); loadRows(); } catch (err) {}
    }

    async function loadRows() {
      const e = entity(), host = document.getElementById('table');
      let rows = [];
      try { rows = await api('/api/' + e.table); } catch (err) { host.innerHTML = '<p class="err">Failed to load records.</p>'; return; }
      const cols = e.fields.map(f => f.name);
      host.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">' +
        '<strong>' + e.name_plural + '</strong><span class="badge">' + rows.length + ' record(s)</span></div>' +
        (rows.length === 0 ? '<p class="muted">No records yet. Add one above.</p>' :
        '<table><thead><tr><th>id</th>' + e.fields.map(f => '<th>' + f.label + '</th>').join('') + '<th></th></tr></thead><tbody>' +
        rows.map(r => '<tr><td>' + r.id + '</td>' + cols.map(c => '<td>' + fmt(r[c]) + '</td>').join('') +
          '<td><button class="del" onclick="onDelete(' + r.id + ')">Delete</button></td></tr>').join('') +
        '</tbody></table>');
    }

    function fmt(v) { if (v === null || v === undefined) return '<span class="muted">—</span>'; return String(v).replace(/[<>&]/g, s => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[s])); }

    boot();
  </script>
</body>
</html>
'''


# --------------------------------------------------------------------------- #
# React + Vite frontend (real developer source, talks to /api/_meta)
# --------------------------------------------------------------------------- #
_FE_PACKAGE_JSON = '''{
  "name": "__SLUG__-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview --host --port 3000"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.0"
  }
}
'''

_FE_VITE_CONFIG = '''import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy API calls to the generated FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
    },
  },
})
'''

_FE_TSCONFIG = '''{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true
  },
  "include": ["src"]
}
'''

_FE_INDEX_HTML = '''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>__APP_TITLE__</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
'''

_FE_VITE_ENV = '/// <reference types="vite/client" />\n'

_FE_MAIN_TSX = '''import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
'''

_FE_API_TS = '''const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface FieldMeta { name: string; label: string; type: string; required: boolean }
export interface EntityMeta { name: string; name_plural: string; table: string; path: string; fields: FieldMeta[] }
export interface AppMeta { app_title: string; description: string; primary_color: string; entities: EntityMeta[] }
export type Record_ = { id: number } & { [key: string]: unknown }

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error('Request failed: ' + res.status)
  return res.json() as Promise<T>
}

export const getMeta = () => fetch(`${BASE}/api/_meta`).then(json<AppMeta>)
export const listRecords = (table: string) => fetch(`${BASE}/api/${table}`).then(json<Record_[]>)
export const createRecord = (table: string, body: Record<string, unknown>) =>
  fetch(`${BASE}/api/${table}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then(json<Record_>)
export const deleteRecord = (table: string, id: number) =>
  fetch(`${BASE}/api/${table}/${id}`, { method: 'DELETE' }).then((r) => {
    if (!r.ok) throw new Error('Delete failed')
  })
'''

_FE_APP_TSX = r'''import { useEffect, useState } from 'react'
import {
  AppMeta, EntityMeta, FieldMeta, Record_,
  getMeta, listRecords, createRecord, deleteRecord,
} from './api'

export default function App() {
  const [meta, setMeta] = useState<AppMeta | null>(null)
  const [active, setActive] = useState<string>('')
  const [error, setError] = useState<string>('')

  useEffect(() => {
    getMeta()
      .then((m) => { setMeta(m); setActive(m.entities[0]?.table ?? '') })
      .catch(() => setError('Could not reach the API at /api/_meta.'))
  }, [])

  if (error) return <div className="state">{error}</div>
  if (!meta) return <div className="state">Loading…</div>

  const entity = meta.entities.find((e) => e.table === active) ?? meta.entities[0]
  return (
    <div className="app" style={{ ['--brand' as string]: meta.primary_color } as React.CSSProperties}>
      <header className="topbar">
        <h1>{meta.app_title}</h1>
        <p>{meta.description}</p>
      </header>
      <nav className="tabs">
        {meta.entities.map((e) => (
          <button key={e.table} className={e.table === active ? 'tab active' : 'tab'} onClick={() => setActive(e.table)}>
            {e.name_plural}
          </button>
        ))}
      </nav>
      {entity && <EntityView key={entity.table} entity={entity} />}
    </div>
  )
}

function coerce(type: string, v: string): unknown {
  if (v === '') return undefined
  if (type === 'integer') return parseInt(v, 10)
  if (type === 'number') return parseFloat(v)
  if (type === 'boolean') return v === 'true'
  return v
}

function inputType(t: string): string {
  if (t === 'integer' || t === 'number') return 'number'
  if (t === 'date') return 'date'
  return 'text'
}

function EntityView({ entity }: { entity: EntityMeta }) {
  const [rows, setRows] = useState<Record_[]>([])
  const [form, setForm] = useState<{ [k: string]: string }>({})
  const [err, setErr] = useState('')

  const refresh = () => listRecords(entity.table).then(setRows).catch(() => setErr('Failed to load records.'))
  useEffect(() => { setForm({}); setErr(''); refresh() /* eslint-disable-next-line */ }, [entity.table])

  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setErr('')
    const body: { [k: string]: unknown } = {}
    for (const f of entity.fields) {
      const val = coerce(f.type, form[f.name] ?? '')
      if (val !== undefined) body[f.name] = val
    }
    try {
      await createRecord(entity.table, body)
      setForm({})
      refresh()
    } catch {
      setErr('Create failed — check required fields.')
    }
  }

  const onDelete = async (id: number) => {
    try { await deleteRecord(entity.table, id); refresh() } catch { /* ignore */ }
  }

  return (
    <section>
      <form className="form" onSubmit={submit}>
        {entity.fields.map((f: FieldMeta) => (
          <div className="field" key={f.name}>
            <label>{f.label}{f.required ? ' *' : ''}</label>
            {f.type === 'boolean' ? (
              <select value={form[f.name] ?? ''} onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}>
                <option value="">—</option>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                type={inputType(f.type)}
                required={f.required}
                value={form[f.name] ?? ''}
                onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
              />
            )}
          </div>
        ))}
        <div className="field"><button className="add" type="submit">Add {entity.name}</button></div>
      </form>
      {err && <p className="err">{err}</p>}

      <div className="count">{rows.length} record(s)</div>
      {rows.length === 0 ? (
        <p className="muted">No records yet. Add one above.</p>
      ) : (
        <table>
          <thead>
            <tr><th>id</th>{entity.fields.map((f) => <th key={f.name}>{f.label}</th>)}<th></th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.id}</td>
                {entity.fields.map((f) => <td key={f.name}>{format(r[f.name])}</td>)}
                <td><button className="del" onClick={() => onDelete(r.id)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function format(v: unknown): string {
  if (v === null || v === undefined) return '—'
  return String(v)
}
'''

_FE_STYLES_CSS = ''':root { --brand: #6d28d9; }
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; background: #0b0f19; color: #e5e7eb; }
.app { min-height: 100vh; }
.state { display: grid; place-items: center; height: 100vh; color: #9ca3af; }
.topbar { padding: 24px 28px; border-bottom: 1px solid rgba(255,255,255,.08); }
.topbar h1 { margin: 0; font-size: 22px; }
.topbar p { margin: 6px 0 0; color: #9ca3af; font-size: 14px; }
section { max-width: 1000px; margin: 0 auto; padding: 24px 28px; }
.tabs { display: flex; gap: 8px; flex-wrap: wrap; padding: 16px 28px 0; max-width: 1000px; margin: 0 auto; }
.tab { background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); color: #cbd5e1; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.tab.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.form { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; align-items: end; background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08); border-radius: 12px; padding: 18px; margin-bottom: 18px; }
.field label { font-size: 12px; color: #9ca3af; display: block; margin-bottom: 4px; }
input, select { width: 100%; padding: 8px 10px; border-radius: 8px; background: #0e1424; border: 1px solid rgba(255,255,255,.1); color: #e5e7eb; font-size: 14px; }
.add { background: var(--brand); color: #fff; border: none; padding: 9px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,.06); }
th { color: #9ca3af; }
.del { background: transparent; border: 1px solid rgba(239,68,68,.4); color: #fca5a5; border-radius: 6px; padding: 4px 8px; cursor: pointer; font-size: 12px; }
.muted { color: #6b7280; font-size: 13px; }
.err { color: #fca5a5; font-size: 13px; }
.count { color: #9ca3af; font-size: 13px; margin: 6px 0 10px; }
'''

_FE_DOCKERFILE = '''FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
'''

_FE_NGINX_CONF = '''server {
  listen 80;
  location /api/ { proxy_pass http://backend:8080; }
  location /health { proxy_pass http://backend:8080; }
  location / {
    root /usr/share/nginx/html;
    try_files $uri /index.html;
  }
}
'''

_FE_DOCKERIGNORE = "node_modules/\ndist/\n"


# --------------------------------------------------------------------------- #
# Root / infra files
# --------------------------------------------------------------------------- #
_COMPOSE = '''services:
  backend:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      - DB_PATH=/data/app.db
    volumes:
      - app-data:/data

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

volumes:
  app-data:
'''

_GITIGNORE = "__pycache__/\n*.db\nnode_modules/\ndist/\n.env\n.venv/\n"


def _readme(spec: AppSpec) -> str:
    entity_lines = "\n".join(
        f"- **{e.name_plural}** — fields: {', '.join(f.name for f in e.fields)}"
        for e in spec.entities
    )
    api_lines = "\n".join(
        f"- `/api/{e.table}` — CRUD for {e.name_plural}" for e in spec.entities
    )
    return f"""# {spec.app_title}

> {spec.description}

_Generated by **VibeForge — Autonomous AI Engineering Team**. This is real, runnable code (FastAPI + SQLite + React/Vite), not documentation._

## Domain model
{entity_lines}

## Project layout
```
{spec.slug}/
├── backend/            FastAPI + SQLite REST API (+ built-in admin console)
│   ├── app/
│   │   ├── main.py        app, CORS, health, /api/_meta
│   │   ├── db.py          sqlite connection + schema
│   │   ├── repository.py  generic CRUD
│   │   ├── schemas.py     Pydantic models
│   │   ├── routers/       one router per entity
│   │   ├── seed.py        startup seed data
│   │   ├── spec.json      the data model
│   │   └── static/        dependency-free admin UI
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           React + TypeScript + Vite client
└── docker-compose.yml
```

## Run with Docker (recommended)
```bash
docker compose up --build
# Frontend  → http://localhost:3000
# Backend   → http://localhost:8080  (admin console + Swagger at /docs)
```

## Run locally (no Docker)
Backend:
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
# open http://localhost:8080  (built-in console)
```
Frontend (separate terminal):
```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (proxies /api to :8080)
```

## API
{api_lines}

Every entity supports `GET` (list), `POST` (create), `GET /{{id}}`, `PUT /{{id}}`, `DELETE /{{id}}`.
"""


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def render_project(spec: AppSpec) -> dict[str, str]:
    """Render the full project as {relative_path: file_content}."""
    files: dict[str, str] = {}

    # ---- backend ----
    files["backend/requirements.txt"] = _REQUIREMENTS
    files["backend/Dockerfile"] = _BACKEND_DOCKERFILE
    files["backend/.dockerignore"] = _BACKEND_DOCKERIGNORE
    files["backend/app/__init__.py"] = ""
    files["backend/app/spec.json"] = _spec_json(spec)
    files["backend/app/db.py"] = _DB_PY
    files["backend/app/repository.py"] = _REPOSITORY_PY
    files["backend/app/schemas.py"] = _schemas_py(spec)
    files["backend/app/seed.py"] = _SEED_PY
    files["backend/app/main.py"] = _MAIN_PY
    files["backend/app/static/index.html"] = _STATIC_INDEX_HTML
    files["backend/app/routers/__init__.py"] = _routers_init_py(spec)
    for e in spec.entities:
        files[f"backend/app/routers/{e.table}.py"] = _router_py(e)

    # ---- frontend ----
    files["frontend/package.json"] = _FE_PACKAGE_JSON.replace("__SLUG__", spec.slug)
    files["frontend/vite.config.ts"] = _FE_VITE_CONFIG
    files["frontend/tsconfig.json"] = _FE_TSCONFIG
    files["frontend/index.html"] = _FE_INDEX_HTML.replace("__APP_TITLE__", spec.app_title)
    files["frontend/.dockerignore"] = _FE_DOCKERIGNORE
    files["frontend/Dockerfile"] = _FE_DOCKERFILE
    files["frontend/nginx.conf"] = _FE_NGINX_CONF
    files["frontend/src/main.tsx"] = _FE_MAIN_TSX
    files["frontend/src/vite-env.d.ts"] = _FE_VITE_ENV
    files["frontend/src/api.ts"] = _FE_API_TS
    files["frontend/src/App.tsx"] = _FE_APP_TSX
    files["frontend/src/styles.css"] = _FE_STYLES_CSS

    # ---- root ----
    files["docker-compose.yml"] = _COMPOSE
    files[".gitignore"] = _GITIGNORE
    files["README.md"] = _readme(spec)

    return files
