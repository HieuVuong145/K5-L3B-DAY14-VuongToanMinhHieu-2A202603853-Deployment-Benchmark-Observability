# Day 14 Lab - Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`
1. API key hardcode trong code. Nếu push lên GitHub → key bị lộ ngay lập tức
2. Không có config management
3. Print thay vì proper logging, log ra secret
4. Không có health check endpoint. Nếu agent crash, platform không biết để restart
5. Port cố định — không đọc từ environment. Trên Railway/Render, PORT được inject qua env var

- **Ví dụ đối chiếu dòng code đã sửa trong `production/app.py`:**
  - `develop/app.py` (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` (hardcode secret).
  - `production/app.py` (dòng 24, 196–198): `from config import settings` và đọc `settings.host`, `settings.port`, `settings.debug` từ biến môi trường (`.env`).
  - `develop/app.py` (dòng 49–53): `host="localhost"`, `port=8000`, `reload=True` và không có `/health`, `/ready` hay xử lý `SIGTERM`.
  - `production/app.py` (dòng 135–161, 180–189): bổ sung `@app.get("/health")`, `@app.get("/ready")` và `signal.signal(signal.SIGTERM, handle_sigterm)`.

### Exercise 1.2: Develop test output
```bash
# curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 1.3: Comparison table
| Feature | Basic (`develop`) | Advanced (`production`) | Tại sao quan trọng? |
|---|---|---|---|
| Config & Secrets | Hardcode trực tiếp (`OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG`, `MAX_TOKENS`) | Đọc từ biến môi trường qua `config.py` (`settings`) | Tránh lộ secret khi push lên Git; dễ đổi cấu hình theo môi trường (dev/staging/prod) mà không cần sửa code. |
| Health check | Không có | Có `/health` (liveness) và `/ready` (readiness, trả `503` khi chưa sẵn sàng) | Platform/Load balancer biết khi nào container treo để restart (`/health`) hoặc khi nào chưa sẵn sàng nhận traffic (`/ready`). |
| Logging | Dùng `print()` và log cả `OPENAI_API_KEY` | Structured JSON logging (`logging`), không log secret | Log JSON dễ parse trên hệ thống tập trung (Loki, Datadog), đồng thời bảo vệ thông tin nhạy cảm. |
| Host & Port | Cố định `host="localhost"`, `port=8000`, `reload=True` | `0.0.0.0`, đọc `PORT` env var, `reload=settings.debug` | `0.0.0.0` mới nhận kết nối từ ngoài container; `PORT` tương thích cloud (Railway/Render); tắt `reload` ở production. |
| Shutdown | Tắt đột ngột | `lifespan` + `signal.signal(signal.SIGTERM, handle_sigterm)` | Đảm bảo request đang xử lý được hoàn thành và dọn tài nguyên sạch sẽ trước khi tắt container (graceful shutdown). |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)
1. **Base image:** python:3.11 = full Python distribution (~1Gb)
2. **Working directory:** /app
3. **Tại sao `COPY requirements.txt` đứng trước `COPY . .`:** Cơ chế Docker layer cache. `requirements.txt` ít thay đổi hơn trong source code; nếu copy và pip install trước, khi sửa `app.py` và build lại, Docker dùng lại layer đã cài thư viện từ cache thay vì `pip install` lại từ đầu
4. **CMD vs ENTRYPOINT khác nhau thế nào:** CMD cung cấp lệnh và tham số mặc định, dễ ghi đè khi chạy `docker run <image> ...`. `ENTRYPOINT` cố định chương trình chính sẽ chạy, tham số truyền thêm vào `docker run` sẽ nối vào sau `ENTRYPOINT`.

### Exercise 2.2: Container test output
```bash
# Dán kết quả gọi container my-agent:develop
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build & Image size comparison
- **Stage 1 làm gì:** Dùng `python:3.11-slim`, cài `gcc`, `libpq-dev` và `pip install --user -r requirements.txt` vào `/root/.local`
- **Stage 2 làm gì:** Dùng `python:3.11-slim` sạch, tạo non-root user `appuser`, chỉ `COPY --from=builder /root/.local` (các package đã biên dịch) + mã nguồn, không mang theo `gcc`, `libpq-dev` hay cache build
- **Tại sao image nhỏ hơn:** Nó an toàn hơn do không chưa compiler hay build tools thừa và dùng base `slim` (nhỏ hơn `python:3.11`); chạy bằng `appuser` (not-root) giảm rủi ro bảo mật.
- **Số đo thực tế (`docker images`):**
  - `my-agent:develop`: `415` MB
  - `my-agent:advanced`: `57.5` MB
  - Chênh lệch: 86%

### Exercise 2.4: Docker Compose stack
- **Sơ đồ kiến trúc các service & cách giao tiếp:**
  ```text
  Client (curl / Browser)
         │
         ▼  HTTP (:80 / :443)
  ┌──────────────────────────────────────────────────────────┐
  │ Docker Bridge Network: internal                          │
  │                                                          │
  │  ┌──────────────┐   HTTP (:8000)   ┌──────────────────┐  │
  │  │    nginx     │ ───────────────► │  agent (FastAPI) │  │
  │  │ (nginx:alpine│                  │  không mở port   │  │
  │  │  reverse     │                  │  ra ngoài host   │  │
  │  │  proxy)      │                  └────┬────────┬────┘  │
  │  └──────────────┘                       │        │       │
  │                                         │        │       │
  │                       redis://redis:6379/0       │ http://qdrant:6333
  │                                         ▼        ▼       │
  │                             ┌────────────┐  ┌──────────┐ │
  │                             │   redis    │  │  qdrant  │ │
  │                             │ (7-alpine) │  │ (v1.9.0) │ │
  │                             └─────┬──────┘  └────┬─────┘ │
  │                                   │              │       │
  │                            [redis_data]    [qdrant_data] │
  │                              (volume)        (volume)    │
  └──────────────────────────────────────────────────────────┘
  ```
  - **Cách giao tiếp:** Các service nằm chung mạng bridge `internal`, gọi nhau bằng **tên service** (DNS nội bộ của Docker Compose). Chỉ `nginx` mở cổng `80`/`443` ra máy host làm reverse proxy; `agent` chỉ khởi động sau khi `redis` và `qdrant` báo `service_healthy`.
- **Kết quả test qua Nginx (`http://localhost/health`, `http://localhost/ask`):**
  ```bash
  # Dán output test
  {"status":"ok","uptime_seconds":207.3,"version":"2.0.0","timestamp":"2026-11-26T03:57:41.742985"}

  {"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
  ```

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy Agent Part 6 lên Railway hoặc Render
- **Nền tảng chọn:** Render
- **Public URL:** `https://k5-l3b-day14-vuongtoanminhhieu.onrender.com`
- **Screenshots:** `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml`
- **Khác nhau chỗ nào & vì sao:**
  - `railway.toml` (định dạng TOML): chỉ khai báo gọn cấu hình build (`[build] builder = "DOCKERFILE"`) và deploy (`[deploy] healthcheckPath = "/health"`), còn biến môi trường, secret và Redis thường cấu hình trực tiếp trên Railway Dashboard hoặc Railway CLI.
  - `render.yaml` (định dạng YAML Blueprint — Infrastructure as Code): khai báo đầy đủ cả dịch vụ (`type: web`, `runtime: docker`, `healthCheckPath: /health`) lẫn danh sách `envVars`, hỗ trợ thuộc tính bảo mật cho secret (`generateValue: true` để Render tự sinh key hoặc `sync: false` để nhập tay trên dashboard mà không lộ vào Git).

### Exercise 3.3: Cloud Run (`03-cloud-deployment/production-cloud-run/`)
- **Mô tả pipeline CI/CD (dựa trên `cloudbuild.yaml` và `service.yaml`):**
  1. Khi push code lên nhánh `main`, Google Cloud Build chạy Step 1 (`test`) dùng image `python:3.11-slim` để cài dependencies và chạy `pytest`.
  2. Nếu test pass, Step 2 (`build`) build Docker image gắn tag `$COMMIT_SHA` và `latest` (tận dụng `--cache-from` để cache layer), rồi Step 3 (`push`) đẩy image lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
  3. Step 4 (`deploy`) chạy `gcloud run deploy` triển khai lên Cloud Run (`asia-southeast1`, `min-instances=1` tránh cold start, `max-instances=10`, inject secret từ Secret Manager).
  4. Song song đó, `service.yaml` định nghĩa cấu hình Knative Service (IaC): giới hạn CPU/RAM (`1` CPU / `512Mi`), `containerConcurrency: 80`, lấy secret qua `secretKeyRef`, cùng `livenessProbe` (`/health`) và `startupProbe` (`/ready`).

---

## Part 4: API Security

### Exercise 4.1–4.3: Test results (`curl -i`, đã che token)

#### 1. `401 Unauthorized` (thiếu `X-API-Key` ở `develop/app.py`)
```http
HTTP/1.1 401 Unauthorized
date: Thu, 26 Nov 2026 07:14:57 GMT
server: uvicorn
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

#### 2. `200 OK` (hợp lệ với JWT của tài khoản `student` ở `POST /auth/token`, đã che `$TOKEN`)
```http
HTTP/1.1 200 OK
date: Thu, 26 Nov 2026 07:14:12 GMT
server: uvicorn
content-length: 215
content-type: application/json
vary: Origin
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin

{"question":"Explain JWT","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic.","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```

#### 3. `429 Too Many Requests` (vượt rate limit 10 req/phút trong vòng lặp ở `production/app.py`)
```text
Request 1..9  -> HTTP 200 OK
Request 10..12 -> HTTP 429 Too Many Requests
```

```http
HTTP/1.1 429 Too Many Requests
date: Thu, 26 Nov 2026 07:14:21 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795677321
retry-after: 51
content-length: 98
content-type: application/json
vary: Origin
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
```

### Exercise 4.4: Cost guard implementation
- **Cách triển khai cost guard:**
  - Theo dõi số `input_tokens` và `output_tokens` tiêu thụ theo từng `user_id` và theo ngày/tháng (quy đổi ra USD theo bảng giá model). Trong bản mẫu `04-api-gateway/production/cost_guard.py` lưu tạm bằng dict in-memory (`UsageRecord`), còn trong production (như Part 6) phải lưu vào **Redis** (key theo `user_id` + ngày/tháng, đặt TTL tự reset) để dùng chung giữa nhiều instance.
  - Luồng xử lý mỗi request: gọi `check_budget(user_id)` **trước** khi gọi LLM (nếu chạm ngưỡng 80% thì log cảnh báo, nếu vượt budget user thì trả `402 Payment Required`, vượt global budget thì trả `503`); **sau** khi LLM trả lời thì gọi `record_usage(user_id, input_tokens, output_tokens)` để cộng dồn chi phí.
- **Vì sao cần cả Rate Limit và Cost Guard:**
  - **Rate Limit** bảo vệ **tốc độ** (số request/phút) để chống spam, brute-force hoặc quá tải CPU/RAM.
  - **Cost Guard** bảo vệ **ngân sách tiền** (USD/token) — vì một user gửi các prompt rất dài hoặc sinh output dài vẫn có thể đốt rất nhiều tiền dù tần suất request nằm dưới ngưỡng rate limit.

---

## Part 5: Scaling & Reliability

### Exercise 5.1–5.5: Implementation notes & test results
- **Liveness (`/health`) khác Readiness (`/ready`) ở đâu:** Liveness trả lời *"Agent còn sống không?"* — nếu trả về non-200 hoặc timeout thì platform sẽ restart container. Còn Readiness trả lời *"Agent đã sẵn sàng nhận traffic chưa?"* — nếu trả về `503` (lúc đang khởi động, đang tắt, hoặc mất kết nối Redis), load balancer sẽ ngưng gửi request mới vào instance đó nhưng không restart.
- **Graceful shutdown hoạt động thế nào:** Khi nhận tín hiệu dừng `SIGTERM`, app đặt `_is_ready = False` để không nhận thêm request mới, rồi đợi `_in_flight_requests` giảm về `0` (tối đa 30s) mới tắt hẳn, tránh cắt ngang request đang xử lý.
- **Vì sao state trong RAM bị hỏng khi chạy nhiều instance:** Do mỗi container có vùng nhớ RAM độc lập nên khi chạy nhiều instance sau Nginx, các request liên tiếp của cùng một user có thể bị chia sang các instance khác nhau. Nếu lưu lịch sử chat, rate limit hay budget trong RAM, instance mới sẽ không thấy dữ liệu của request trước, và khi container restart thì toàn bộ state trong RAM cũng mất theo.
- **Kết quả chạy `docker compose -p k5-day14-scaling up -d --build --scale agent=3` và `python3 test_stateless.py`:**

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: c7f81702-4dc1-49b6-a4fa-bada21999b14

Request 1: [instance-07e56f]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-3ac44b]
  Q: Why do we need containers?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 3: [instance-7625be]
  Q: What is Kubernetes?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 4: [instance-07e56f]
  Q: How does load balancing work?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 5: [instance-3ac44b]
  Q: What is Redis used for?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-07e56f', 'instance-7625be', 'instance-3ac44b'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Kubernetes?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: How does load balancing work?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: What is Redis used for?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...

✅ Session history preserved across all instances via Redis!
```

- **Giải thích kết quả:** 5 request trong cùng một `session_id` được Nghinx cân bằng tải luân phiên qua cả 3 container khác nhau `instance-07e56f/3ac44b/7625be`. Nhưng khi gọi `/chat/{session_id}/history` vẫn thu được đầy đủ 10 tin nhắn gồm 5 câu hỏi `user` và 5 câu trả lời `assistant` theo đúng thứ tự. Chứng tỏ agent đã **stateless** nghĩa là mọi state của session được lưu tập trung bên ngoài trong Redis để tất cả instance cùng đọc/ghi chung.

---

## Part 6: Final Project

### Output `python check_production_ready.py` (phần "📋 Checklist Deliverable")
```text
# Dán phần Checklist Deliverable khi đạt PASS 12/12
📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
```

---

## AI Log
| Bước / Phần | Đã hỏi AI gì | Nhận được gì | Bạn tự sửa & tự kiểm tra thế nào |
|---|---|---|---|
| Part 1 (CP1) | Gợi ý bảng so sánh `develop` vs `production` | Bảng so sánh Exercise 1.3 | So sánh những điểm khác nhau rồi điều chỉnh |
| Part 2 (CP2) | Kiểm tra Part 2 và vẽ sơ đồ Docker Compose (Exercise 2.4) | Sơ đồ kiến trúc 4 service (`nginx`, `agent`, `redis`, `qdrant`) và giải thích giao tiếp | Tự build/chạy container, đo `docker images`, test Nginx và đối chiếu với `docker-compose.yml` |
| Part 4 (CP3) | Thực hiện test Exercise 4.1–4.3 và giải thích Cost Guard (4.4) | Output thật `401`, `200`, `429` (đã che token) và giải thích cơ chế `CostGuard` | Đọc lại `develop/app.py`, `production/app.py`, `cost_guard.py` và kiểm tra kết quả trong `MISSION_ANSWERS.md` |
| Part 6 (CP5) | Cài `.venv` Python 3.11, sửa lỗi `auth.py` và hoàn thiện các `TODO` trong `06-lab-complete/` | Code hoàn chỉnh `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, `railway.toml`, `render.yaml` | Đọc hiểu toàn bộ code và chạy `python check_production_ready.py` đạt `PASS 12/12` (43/43 checks) |
| Part 3 (CP6) | Gợi ý deploy Render, so sánh `railway.toml` vs `render.yaml`, mô tả Cloud Run | Hướng dẫn deploy Render + tạo `DEPLOYMENT.md` + so sánh config & tóm tắt `cloudbuild.yaml`/`service.yaml` | Tự tạo Redis + Web Service trên Render, test 4 mã HTTP (`200/200/401/200`) và chụp 3 ảnh trong `screenshots/` |
| Part 7 (CP7–CP8) | Chạy `MOCK_SLOW_RATE`, `eval`, sửa Dockerfile `PYTHONPATH`, chụp ảnh Grafana/Jaeger/Prometheus và tổng hợp `BENCHMARK_REPORT.md` | Bộ JSON `reports/`, CSV `benchmark-results/`, 4 ảnh observability và báo cáo số liệu khớp JSON/CSV | Tự chạy 4 mức concurrency, kiểm tra lại toàn bộ số liệu trong `BENCHMARK_REPORT.md` |
