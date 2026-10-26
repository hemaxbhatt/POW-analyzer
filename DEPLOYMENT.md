# Production Deployment Guide — Proof-of-Work Analyzer

## 1. Quick Start with Docker

### Prerequisites
* Docker 24.0+ & Docker Compose v2+
* `.env` file configured with your API credentials:
  ```env
  GEMINI_API_KEY=your_gemini_api_key
  ANTHROPIC_API_KEY=optional_fallback_key
  AWS_ACCESS_KEY_ID=optional_for_s3
  AWS_SECRET_ACCESS_KEY=optional_for_s3
  AWS_DEFAULT_REGION=ap-south-1
  S3_BUCKET_NAME=your_bucket_name
  ```

### Build & Run
```bash
docker compose up -d --build
```

### Check Logs & Health
```bash
docker compose logs -f
curl http://localhost:8000/health
```

---

## 2. API Endpoints for Portal Integration

The PHP / Next.js frontend interacts with the following endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Healthcheck (returns `{"status": "ok"}`) |
| `POST` | `/analyze` | Production trigger using S3 video/photo keys |
| `POST` | `/test/local-analyze` | Testing trigger with local video/photo paths |
| `GET` | `/submissions/{id}/result` | Poll submission status and retrieve final report |

---

## 3. Data Retention & Disk Management
Job artifacts (extracted frames, audio, and `result.json`) are stored in `/app/data/{submission_id}`. 
A cronjob or scheduled task should archive or clean up folders older than 7 days to preserve disk space:
```bash
find ./data -maxdepth 1 -type d -mtime +7 -exec rm -rf {} +
```
