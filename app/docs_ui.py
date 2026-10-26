"""
Custom dark-mode Swagger UI renderer.

Returns a fully self-contained HTML page that loads Swagger UI from CDN
and applies a polished dark theme with complete coverage of all elements —
including dynamically rendered schema boxes, "Expand" buttons, and tables.
"""

DOCS_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Proof-of-Work Analyzer · API Docs</title>
  <link rel="icon" href="https://fastapi.tiangolo.com/img/favicon.png" />
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  <style>
    /* ═══════════════════════════════════════════════════════════
       HEMAX · Proof-of-Work Analyzer — Custom Dark Swagger UI
       ═══════════════════════════════════════════════════════════ */

    :root {
      --bg-base:    #0d0f17;
      --bg-card:    #12151f;
      --bg-raised:  #181c28;
      --bg-input:   #1a1e2e;
      --border:     #252a3d;
      --border-light: #2e3450;
      --text:       #dde3f0;
      --text-muted: #5f6b8a;
      --text-dim:   #8896b3;
      --accent:     #6c8ff5;
      --accent-glow:rgba(108,143,245,0.25);
      --green:      #3ecf74;
      --green-bg:   #0a1f14;
      --blue:       #38bdf8;
      --blue-bg:    #071926;
      --amber:      #fbbf24;
      --red:        #f87171;
      --red-bg:     #1f0a0a;
      --purple:     #a78bfa;
      --radius:     10px;
      --radius-sm:  6px;
    }

    /* ── Base ─────────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      background: var(--bg-base) !important;
      color: var(--text) !important;
      font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif !important;
      font-size: 14px;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }

    /* ── Swagger wrapper ──────────────────────────────────── */
    .swagger-ui { background: var(--bg-base) !important; color: var(--text) !important; }
    .swagger-ui * { color: inherit; }

    /* ── Top bar ──────────────────────────────────────────── */
    .swagger-ui .topbar {
      background: var(--bg-card) !important;
      border-bottom: 1px solid var(--border) !important;
      padding: 10px 28px !important;
    }
    .swagger-ui .topbar-wrapper { display: flex; align-items: center; gap: 16px; }
    .swagger-ui .topbar-wrapper img,
    .swagger-ui .topbar-wrapper svg { height: 30px !important; filter: brightness(0) invert(0.9); }
    .swagger-ui .topbar .download-url-wrapper { flex: 1; }
    .swagger-ui .topbar .download-url-wrapper input[type=text] {
      background: var(--bg-input) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: var(--radius-sm) !important;
      color: var(--text) !important;
      padding: 7px 12px !important;
      font-size: 0.85rem !important;
      width: 100%;
    }
    .swagger-ui .topbar .download-url-wrapper .download-url-button {
      background: var(--accent) !important;
      border: none !important;
      border-radius: var(--radius-sm) !important;
      color: #fff !important;
      font-weight: 600 !important;
      padding: 7px 16px !important;
      cursor: pointer;
    }

    /* ── Info section ─────────────────────────────────────── */
    .swagger-ui .information-container {
      background: var(--bg-base) !important;
      padding: 24px 28px 0 !important;
    }
    .swagger-ui .info {
      background: linear-gradient(135deg, #131726 0%, #0f1220 100%) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: 14px !important;
      padding: 28px 32px !important;
      margin: 0 !important;
      position: relative;
      overflow: hidden;
    }
    .swagger-ui .info::before {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: linear-gradient(90deg, var(--accent), var(--purple), var(--blue));
      border-radius: 14px 14px 0 0;
    }
    .swagger-ui .info .title {
      font-size: 1.85rem !important;
      font-weight: 700 !important;
      color: #fff !important;
      letter-spacing: -0.5px !important;
      line-height: 1.2 !important;
      margin-bottom: 8px !important;
    }
    .swagger-ui .info .version-stamp,
    .swagger-ui .info .version {
      background: rgba(108,143,245,0.15) !important;
      color: var(--accent) !important;
      border: 1px solid rgba(108,143,245,0.3) !important;
      border-radius: 20px !important;
      padding: 2px 12px !important;
      font-size: 0.72rem !important;
      font-weight: 600 !important;
      letter-spacing: 0.5px !important;
      text-transform: uppercase !important;
    }
    .swagger-ui .info p,
    .swagger-ui .info li,
    .swagger-ui .info .description p {
      color: var(--text-dim) !important;
      font-size: 0.9rem !important;
      margin-top: 10px !important;
    }
    .swagger-ui .info a { color: var(--accent) !important; }

    /* ── Wrapper / content area ───────────────────────────── */
    .swagger-ui .wrapper {
      background: var(--bg-base) !important;
      padding: 20px 28px !important;
      max-width: 1200px !important;
    }

    /* ── Scheme container ─────────────────────────────────── */
    .swagger-ui .scheme-container {
      background: var(--bg-card) !important;
      border-bottom: 1px solid var(--border) !important;
      padding: 12px 28px !important;
      box-shadow: none !important;
    }
    .swagger-ui .scheme-container .schemes > label {
      color: var(--text-muted) !important;
      font-size: 0.75rem !important;
      font-weight: 600 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.5px !important;
    }
    .swagger-ui select,
    .swagger-ui .schemes select {
      background: var(--bg-input) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: var(--radius-sm) !important;
      color: var(--text) !important;
      padding: 6px 10px !important;
      font-size: 0.85rem !important;
      -webkit-appearance: none;
    }

    /* ── Tags (group headers) ─────────────────────────────── */
    .swagger-ui .opblock-tag-section { margin-bottom: 8px !important; }
    .swagger-ui .opblock-tag {
      border: none !important;
      border-bottom: 1px solid var(--border) !important;
      color: var(--text) !important;
      font-size: 1rem !important;
      font-weight: 700 !important;
      padding: 18px 0 12px !important;
      letter-spacing: -0.2px !important;
      background: transparent !important;
      display: flex !important;
      align-items: center !important;
      gap: 10px !important;
    }
    .swagger-ui .opblock-tag:hover { background: rgba(255,255,255,0.02) !important; }
    .swagger-ui .opblock-tag small {
      color: var(--text-muted) !important;
      font-size: 0.8rem !important;
      font-weight: 400 !important;
    }
    .swagger-ui .opblock-tag svg { fill: var(--text-muted) !important; }

    /* ── Operation blocks ─────────────────────────────────── */
    .swagger-ui .opblock {
      border-radius: var(--radius) !important;
      margin-bottom: 8px !important;
      border-width: 1px !important;
      border-style: solid !important;
      box-shadow: 0 2px 12px rgba(0,0,0,0.35) !important;
      overflow: hidden !important;
      transition: box-shadow 0.2s !important;
    }
    .swagger-ui .opblock:hover {
      box-shadow: 0 4px 20px rgba(0,0,0,0.5) !important;
    }
    .swagger-ui .opblock.is-open { box-shadow: 0 6px 24px rgba(0,0,0,0.5) !important; }

    /* POST */
    .swagger-ui .opblock.opblock-post {
      background: var(--blue-bg) !important;
      border-color: rgba(56,189,248,0.25) !important;
    }
    .swagger-ui .opblock.opblock-post .opblock-summary {
      background: var(--blue-bg) !important;
    }
    .swagger-ui .opblock.opblock-post .opblock-summary-method {
      background: var(--blue) !important; color: #000 !important;
    }

    /* GET */
    .swagger-ui .opblock.opblock-get {
      background: var(--green-bg) !important;
      border-color: rgba(62,207,116,0.25) !important;
    }
    .swagger-ui .opblock.opblock-get .opblock-summary {
      background: var(--green-bg) !important;
    }
    .swagger-ui .opblock.opblock-get .opblock-summary-method {
      background: var(--green) !important; color: #000 !important;
    }

    /* DELETE */
    .swagger-ui .opblock.opblock-delete {
      background: var(--red-bg) !important;
      border-color: rgba(248,113,113,0.25) !important;
    }
    .swagger-ui .opblock.opblock-delete .opblock-summary {
      background: var(--red-bg) !important;
    }
    .swagger-ui .opblock.opblock-delete .opblock-summary-method {
      background: var(--red) !important; color: #000 !important;
    }

    /* PUT */
    .swagger-ui .opblock.opblock-put {
      background: #1a1200 !important;
      border-color: rgba(251,191,36,0.25) !important;
    }
    .swagger-ui .opblock.opblock-put .opblock-summary { background: #1a1200 !important; }
    .swagger-ui .opblock.opblock-put .opblock-summary-method {
      background: var(--amber) !important; color: #000 !important;
    }

    /* PATCH */
    .swagger-ui .opblock.opblock-patch {
      background: #110d1e !important;
      border-color: rgba(167,139,250,0.25) !important;
    }
    .swagger-ui .opblock.opblock-patch .opblock-summary { background: #110d1e !important; }
    .swagger-ui .opblock.opblock-patch .opblock-summary-method {
      background: var(--purple) !important; color: #000 !important;
    }

    /* ── Operation summary row ────────────────────────────── */
    .swagger-ui .opblock-summary {
      border: none !important;
      padding: 13px 18px !important;
      cursor: pointer !important;
      display: flex !important;
      align-items: center !important;
      gap: 12px !important;
    }
    .swagger-ui .opblock-summary-method {
      border-radius: var(--radius-sm) !important;
      font-size: 0.68rem !important;
      font-weight: 800 !important;
      min-width: 68px !important;
      text-align: center !important;
      padding: 5px 8px !important;
      letter-spacing: 0.8px !important;
      text-transform: uppercase !important;
      flex-shrink: 0 !important;
    }
    .swagger-ui .opblock-summary-path {
      font-family: 'Fira Code', 'Cascadia Code', monospace !important;
      font-size: 0.9rem !important;
      color: var(--text) !important;
      font-weight: 500 !important;
    }
    .swagger-ui .opblock-summary-path .nostyle { color: var(--text) !important; }
    .swagger-ui .opblock-summary-description {
      color: var(--text-muted) !important;
      font-size: 0.82rem !important;
      margin-left: auto !important;
    }
    .swagger-ui .opblock-summary svg { fill: var(--text-muted) !important; }

    /* ── Expanded operation body ──────────────────────────── */
    .swagger-ui .opblock-body {
      background: var(--bg-base) !important;
      border-top: 1px solid var(--border) !important;
    }
    .swagger-ui .opblock-section-header {
      background: var(--bg-card) !important;
      border-bottom: 1px solid var(--border) !important;
      padding: 10px 18px !important;
    }
    .swagger-ui .opblock-section-header h4,
    .swagger-ui .opblock-section-header label {
      color: var(--text-dim) !important;
      font-size: 0.75rem !important;
      font-weight: 700 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.6px !important;
    }
    .swagger-ui .opblock-description-wrapper {
      padding: 14px 18px !important;
    }
    .swagger-ui .opblock-description-wrapper p {
      color: var(--text-dim) !important;
      font-size: 0.88rem !important;
    }

    /* ── Parameters table ─────────────────────────────────── */
    .swagger-ui .parameters-container { padding: 0 !important; }
    .swagger-ui table {
      background: transparent !important;
      border-collapse: collapse !important;
      width: 100% !important;
    }
    .swagger-ui table thead tr th,
    .swagger-ui table thead tr td {
      background: var(--bg-raised) !important;
      color: var(--text-muted) !important;
      border-bottom: 1px solid var(--border-light) !important;
      font-size: 0.7rem !important;
      text-transform: uppercase !important;
      letter-spacing: 0.6px !important;
      padding: 10px 14px !important;
      font-weight: 700 !important;
    }
    .swagger-ui table tbody tr { background: transparent !important; }
    .swagger-ui table tbody tr td {
      background: transparent !important;
      border-bottom: 1px solid var(--border) !important;
      color: var(--text) !important;
      padding: 12px 14px !important;
      vertical-align: top !important;
    }
    .swagger-ui table tbody tr:last-child td { border-bottom: none !important; }
    .swagger-ui table tbody tr:hover td { background: var(--bg-raised) !important; }

    .swagger-ui .parameter__name {
      color: var(--accent) !important;
      font-family: 'Fira Code', monospace !important;
      font-size: 0.88rem !important;
      font-weight: 600 !important;
    }
    .swagger-ui .parameter__name.required::after {
      color: var(--red) !important;
    }
    .swagger-ui .parameter__type {
      color: var(--purple) !important;
      font-size: 0.78rem !important;
      font-family: 'Fira Code', monospace !important;
    }
    .swagger-ui .parameter__in {
      background: var(--bg-raised) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: 4px !important;
      padding: 1px 6px !important;
      color: var(--text-muted) !important;
      font-size: 0.7rem !important;
      font-weight: 600 !important;
      text-transform: uppercase !important;
      letter-spacing: 0.3px !important;
    }
    .swagger-ui .parameter__deprecated { color: var(--text-muted) !important; }

    /* ── Textareas / inputs ───────────────────────────────── */
    .swagger-ui textarea,
    .swagger-ui input[type=text],
    .swagger-ui input[type=password],
    .swagger-ui input[type=search] {
      background: var(--bg-input) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: var(--radius-sm) !important;
      color: var(--text) !important;
      font-family: 'Fira Code', monospace !important;
      font-size: 0.83rem !important;
      padding: 10px 12px !important;
      transition: border-color 0.15s, box-shadow 0.15s !important;
    }
    .swagger-ui textarea:focus,
    .swagger-ui input:focus {
      border-color: var(--accent) !important;
      outline: none !important;
      box-shadow: 0 0 0 3px var(--accent-glow) !important;
    }

    /* ── Content type selector ────────────────────────────── */
    .swagger-ui .content-type {
      background: var(--bg-input) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: var(--radius-sm) !important;
      color: var(--text) !important;
      padding: 5px 10px !important;
      font-size: 0.82rem !important;
    }

    /* ── Buttons ──────────────────────────────────────────── */
    .swagger-ui .btn {
      border-radius: var(--radius-sm) !important;
      font-weight: 600 !important;
      font-size: 0.82rem !important;
      padding: 7px 16px !important;
      transition: all 0.15s ease !important;
      cursor: pointer !important;
      letter-spacing: 0.2px !important;
    }
    .swagger-ui .btn.execute {
      background: linear-gradient(135deg, #4b6cf7, var(--accent)) !important;
      border: none !important;
      color: #fff !important;
      box-shadow: 0 2px 10px rgba(108,143,245,0.35) !important;
    }
    .swagger-ui .btn.execute:hover {
      transform: translateY(-1px) !important;
      box-shadow: 0 5px 18px rgba(108,143,245,0.5) !important;
    }
    .swagger-ui .btn.execute:active { transform: translateY(0) !important; }
    .swagger-ui .btn.try-out__btn {
      background: transparent !important;
      border: 1px solid var(--border-light) !important;
      color: var(--text-dim) !important;
    }
    .swagger-ui .btn.try-out__btn:hover {
      border-color: var(--accent) !important;
      color: var(--accent) !important;
    }
    .swagger-ui .btn.authorize {
      background: transparent !important;
      border: 1px solid var(--green) !important;
      color: var(--green) !important;
    }
    .swagger-ui .btn.authorize:hover { background: rgba(62,207,116,0.08) !important; }
    .swagger-ui .btn.cancel {
      background: transparent !important;
      border: 1px solid var(--red) !important;
      color: var(--red) !important;
    }
    .swagger-ui .btn-clear,
    .swagger-ui .btn.btn-clear {
      background: transparent !important;
      border: 1px solid var(--border-light) !important;
      color: var(--text-muted) !important;
    }

    /* "Try it out" button */
    .swagger-ui .try-out { padding: 10px 18px !important; }

    /* ── Response section ─────────────────────────────────── */
    .swagger-ui .responses-inner { padding: 0 !important; }
    .swagger-ui .responses-wrapper { background: transparent !important; }
    .swagger-ui .response-col_status { color: var(--green) !important; font-weight: 700 !important; font-size: 0.95rem !important; }
    .swagger-ui .response-col_description { color: var(--text-dim) !important; }

    .swagger-ui .highlight-code,
    .swagger-ui .microlight {
      background: var(--bg-raised) !important;
      border-radius: var(--radius-sm) !important;
      padding: 14px !important;
      font-family: 'Fira Code', monospace !important;
      font-size: 0.8rem !important;
      color: var(--text) !important;
      line-height: 1.7 !important;
    }
    .swagger-ui .response-body pre,
    .swagger-ui pre {
      background: var(--bg-raised) !important;
      color: var(--text) !important;
      border-radius: var(--radius-sm) !important;
      padding: 14px !important;
      font-family: 'Fira Code', monospace !important;
      font-size: 0.8rem !important;
      overflow-x: auto !important;
    }
    .swagger-ui .curl { background: var(--bg-raised) !important; }

    /* ── Code syntax colors ───────────────────────────────── */
    .swagger-ui .microlight .string { color: #7ec8a0 !important; }
    .swagger-ui .microlight .number { color: #e09b3d !important; }
    .swagger-ui .microlight .null   { color: #a78bfa !important; }
    .swagger-ui .microlight .boolean { color: #38bdf8 !important; }

    /* ── Schema / Models section ──────────────────────────── */
    .swagger-ui section.models {
      background: var(--bg-base) !important;
      border: 1px solid var(--border) !important;
      border-radius: var(--radius) !important;
      margin-top: 20px !important;
      overflow: hidden !important;
    }
    .swagger-ui section.models h4 {
      color: var(--text) !important;
      font-size: 1rem !important;
      font-weight: 700 !important;
      padding: 14px 20px !important;
      background: var(--bg-card) !important;
      border-bottom: 1px solid var(--border) !important;
      cursor: pointer !important;
      margin: 0 !important;
    }
    .swagger-ui section.models h4 svg { fill: var(--text-muted) !important; }
    .swagger-ui section.models .model-container {
      background: var(--bg-base) !important;
      border-top: 1px solid var(--border) !important;
      margin: 0 !important;
      padding: 14px 20px !important;
    }
    .swagger-ui section.models .model-container:first-of-type { border-top: none !important; }
    .swagger-ui .model-box,
    .swagger-ui .model {
      background: var(--bg-raised) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: var(--radius-sm) !important;
      padding: 10px 14px !important;
    }
    .swagger-ui .model-title,
    .swagger-ui .model-title__text {
      color: var(--accent) !important;
      font-size: 0.88rem !important;
      font-weight: 600 !important;
      font-family: 'Fira Code', monospace !important;
    }
    .swagger-ui .prop-type   { color: var(--purple) !important; font-family: 'Fira Code', monospace !important; }
    .swagger-ui .prop-format { color: var(--text-muted) !important; font-family: 'Fira Code', monospace !important; }
    .swagger-ui .prop-name   { color: var(--text) !important; font-weight: 600 !important; font-family: 'Fira Code', monospace !important; }
    .swagger-ui .model span,
    .swagger-ui .model-toggle { color: var(--text-dim) !important; }

    /* Expand/Collapse model toggle buttons */
    .swagger-ui .model-toggle { cursor: pointer !important; }
    .swagger-ui .model-toggle::after { color: var(--accent) !important; }

    /* Schema "span" text inside model boxes */
    .swagger-ui .model .property.primitive { color: var(--text-dim) !important; }
    .swagger-ui span.model-title { color: var(--accent) !important; }
    .swagger-ui .models-control { background: transparent !important; border: none !important; color: var(--text-muted) !important; }

    /* ── The white "Expand >" buttons in Schemas ──────────── */
    .swagger-ui button,
    .swagger-ui .expand-methods,
    .swagger-ui .expand-operation {
      background: transparent !important;
      color: var(--text-dim) !important;
    }
    .swagger-ui button[data-name="expand"],
    .swagger-ui button.model-box-control,
    .swagger-ui .model-box-control {
      background: var(--bg-raised) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: 4px !important;
      color: var(--text-dim) !important;
      font-size: 0.72rem !important;
      padding: 2px 8px !important;
      cursor: pointer !important;
    }
    /* Every span inside schema area */
    .swagger-ui .model-container span,
    .swagger-ui .model-box span,
    .swagger-ui .model span {
      color: var(--text-dim) !important;
    }

    /* ── Links ────────────────────────────────────────────── */
    .swagger-ui a,
    .swagger-ui .link { color: var(--accent) !important; text-decoration: none !important; }
    .swagger-ui a:hover { color: #9bb5f9 !important; text-decoration: underline !important; }

    /* ── SVG icons ────────────────────────────────────────── */
    .swagger-ui svg { fill: currentColor !important; }

    /* ── Authorize modal ──────────────────────────────────── */
    .swagger-ui .dialog-ux .modal-ux {
      background: var(--bg-card) !important;
      border: 1px solid var(--border-light) !important;
      border-radius: 12px !important;
      color: var(--text) !important;
    }
    .swagger-ui .dialog-ux .modal-ux-header {
      background: var(--bg-raised) !important;
      border-bottom: 1px solid var(--border) !important;
      border-radius: 12px 12px 0 0 !important;
      padding: 16px 20px !important;
    }
    .swagger-ui .dialog-ux .modal-ux-header h3 {
      color: var(--text) !important;
      font-weight: 700 !important;
    }
    .swagger-ui .dialog-ux .modal-ux-content { padding: 20px !important; }
    .swagger-ui .dialog-ux .modal-ux-content p,
    .swagger-ui .dialog-ux .modal-ux-content label {
      color: var(--text-dim) !important;
    }

    /* ── Loading ──────────────────────────────────────────── */
    .swagger-ui .loading-container .loading::after {
      border-color: var(--accent) transparent !important;
    }

    /* ── Scrollbar ────────────────────────────────────────── */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: var(--bg-base); }
    ::-webkit-scrollbar-thumb { background: var(--border-light); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

    /* ── Tab pills (Example Value / Schema) ───────────────── */
    .swagger-ui .tab li {
      color: var(--text-muted) !important;
      font-size: 0.8rem !important;
      font-weight: 600 !important;
      padding: 6px 12px !important;
      border-radius: var(--radius-sm) !important;
      cursor: pointer !important;
    }
    .swagger-ui .tab li.active {
      color: var(--accent) !important;
      background: rgba(108,143,245,0.1) !important;
    }
    .swagger-ui .tab li button {
      color: inherit !important;
      background: transparent !important;
      border: none !important;
    }

    /* ── Response status codes ────────────────────────────── */
    .swagger-ui .responses-table .response-col_status { min-width: 80px !important; }
    .swagger-ui table.responses-table tbody tr td:first-child { color: var(--green) !important; font-weight: 700 !important; font-family: 'Fira Code', monospace !important; }

    /* ── "No parameters" message ──────────────────────────── */
    .swagger-ui .opblock-body .no-margin { padding: 14px 18px !important; color: var(--text-muted) !important; font-size: 0.85rem !important; }

    /* ── Deprecated badge ─────────────────────────────────── */
    .swagger-ui .opblock.opblock-deprecated { opacity: 0.6 !important; }
    .swagger-ui .opblock.opblock-deprecated .opblock-summary-method { background: var(--text-muted) !important; }

    /* ── Body content wrapper ─────────────────────────────── */
    .swagger-ui .opblock-body .body-param-options { padding: 12px 18px !important; }

    /* ── Checkbox ─────────────────────────────────────────── */
    .swagger-ui .checkbox input[type=checkbox] { accent-color: var(--accent); }
    .swagger-ui .checkbox span { color: var(--text-dim) !important; font-size: 0.83rem !important; }
  </style>
</head>
<body>
  <div id="swagger-ui"></div>

  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = () => {
      SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: "#swagger-ui",
        presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
        layout: "StandaloneLayout",
        deepLinking: true,
        defaultModelsExpandDepth: 1,
        defaultModelExpandDepth: 2,
        displayRequestDuration: true,
        filter: false,
        tryItOutEnabled: false,
        syntaxHighlight: { activated: true, theme: "agate" },
      });
    };
  </script>
</body>
</html>
'''
