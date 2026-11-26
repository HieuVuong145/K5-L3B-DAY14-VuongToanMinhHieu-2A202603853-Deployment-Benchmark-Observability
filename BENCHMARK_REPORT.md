# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Vương Toàn Minh Hiếu
**Ngày chạy:** 2026-11-26
**Môi trường:** macOS (Apple Silicon), Python 3.11.18, Docker Desktop

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | `< 500 ms` | Đảm bảo 95% người dùng nhận phản hồi dưới 0.5 giây, đủ mượt cho trải nghiệm chat tương tác (trong khi vẫn chừa dư địa cho mock retrieval + LLM ~180–220ms). |
| Error rate `/ask` | `< 2.0 %` | Cho phép error budget 2% để hấp thụ lỗi thoáng qua từ upstream LLM (`MOCK_ERROR_RATE` mặc định 1%) mà không gây báo động giả. |
| Accuracy trên golden dataset | `≥ 80%` (mục tiêu `100%` sau sửa KB) | Đảm bảo chất lượng trả lời đạt chuẩn trước khi deploy và không bị regression so với phiên bản trước. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.39 | 193.6 | 222.7 | 1681.1 | 0.67% | ✅ PASS |
| 10 | 35.51 | 192.6 | 221.1 | 1696.0 | 1.00% | ✅ PASS |
| 50 | 108.08 | 196.3 | 265.3 | 1708.5 | 1.67% | ✅ PASS |
| 100 | 49.99 | 447.5 | 4101.8 | 4727.9 | 1.67% | ❌ FAIL |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Không tăng tuyến tính. Từ concurrency 1 → 10 → 50, RPS tăng mạnh (`4.39` → `35.51` → `108.08 req/s`) nhờ tận dụng xử lý bất đồng bộ (`async`). Nhưng khi tăng lên **100**, RPS tụt xuống còn `49.99 req/s` và latency p95 nhảy vọt từ `265.3ms` lên **`4101.8ms`** (vi phạm SLO `< 500ms`) do quá tải event loop / CPU trên 1 process uvicorn duy nhất khiến các request phải xếp hàng chờ lâu.

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.1 | 219.0 | 222.2 |
| 0.03 (mặc định) | 242.9 | 218.9 | 1704.5 |
| 0.1 | 298.6 | 1672.0 | 1712.1 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **p99** (và **p95** khi tỉ lệ chậm vượt 5%) nhạy nhất với request chậm: chỉ cần `MOCK_SLOW_RATE=0.03` (3% request chậm), p99 đã vọt từ `222.2ms` lên `1704.5ms`; ở `0.1` (10% chậm), cả p95 cũng vọt lên `1672.0ms` (FAIL SLO).
- Trong khi đó, **average** ở mức `0.1` chỉ là `298.6ms` — nhìn bề ngoài vẫn tưởng rất nhanh dù 10% người dùng phải chờ gần 1.7 giây. Vì vậy SLO phải đặt theo **p95/p99** để không bị giá trị trung bình che giấu tail latency.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.7 | 108.7 | 112.8 |
| Tổng cost (USD) | $0.000398 | $0.000756 | $0.000783 |
| Cost / câu đúng (USD) | $0.00039795 | $0.00003599 | $0.00003404 |
| Quality gate | ❌ FAIL | ✅ PASS (ngưỡng 80%) | ✅ PASS (ngưỡng 100%) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Bổ sung entry `(["jwt", "api key"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (và `production/utils/mock_llm.py`), giải thích JWT là token có chữ ký số và thời gian hết hạn. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Bổ sung entry `(["kubernetes", "hpa"], ...)` vào `KNOWLEDGE_BASE`, giải thích HPA scale theo CPU, memory hoặc custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2 (và cách chặn merge trong CI):**

- **Trade-off:** v2 (có RAG retrieval) dùng gần gấp đôi số token (`112.8` vs `56.7` tokens/câu) và chậm hơn ~23–35ms ở p95, nhưng accuracy nhảy vọt từ **4.3% → 100%**. Nhờ vậy, **cost / câu đúng** của v2 (`$0.00003404`) thực tế **rẻ hơn ~11.7 lần** so với v1 (`$0.00039795`).
- **Quality gate trong CI:** Trong pipeline CI (vd GitHub Actions), chạy `python eval/run_eval.py --url ... --min-accuracy 1.0 --baseline reports/eval_v2.json`: nếu accuracy thấp hơn ngưỡng hoặc có bất kỳ câu nào bị regression, script thoát với **exit code khác 0** (`exit 1`) để tự động chặn merge PR/deploy.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png` — thấy rõ 4 Golden Signals & LLM panels)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png` — thấy rõ span `chat mock-llm-small` chiếm ~98.8%)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png` — HTTP `503` kèm dấu lỗi trên `POST /ask`, `agent.run`, `chat mock-llm-small`)
- [x] Trang Alerts của Prometheus với ≥ 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png` — `AgentInstanceDown` và `LLMCostBurnRateHigh` cùng firing)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.25` (khi chạy tải) | `AgentHighErrorRate` (`pending` trong lúc test, điều kiện `> 5%` `for: 1m`) | ~1 phút sau khi error rate vượt 5% | `Error rate` & `Requests/s theo status code` (vàng `503`) |
| B | `MOCK_SLOW_RATE=0.3` (khi chạy tải) | `AgentHighLatencyP95` (`pending` ở `t=16s`, điều kiện `p95 > 1s` `for: 2m`) | ~2 phút nếu tải duy trì liên tục | `Latency /ask — p50 / p95 / p99` & `LLM latency p95` |
| C | `LLM_MODEL=mock-llm-large` (chạy tải Locust) | `LLMCostBurnRateHigh` | `pending` tại `t=61s`, **`firing` tại `t≈180s`** (`for: 2m`) | `Cost burn rate (USD/giờ)` & `LLM cost` |
| D | `docker pause` 1 instance agent | `AgentInstanceDown` | `pending` tại `t=16s`, **`firing` tại `t=46s`** (`for: 30s`) | `Instances` (tụt xuống) |
| E | `AGENT_VERSION=v1` | *Không có alert nào firing* (vì HTTP vẫn `200`, latency còn nhanh hơn v2) | — | Không thấy trên infra dashboard |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

- Chạy **eval tự động định kỳ** (scheduled job / canary eval) trên golden dataset hoặc một tập mẫu traffic thật (LLM-as-a-judge) để theo dõi `eval_accuracy` như một metric và đặt alert khi accuracy giảm.
- Kết hợp theo dõi **chỉ số nghiệp vụ phía người dùng** (tỉ lệ thumbs-down, tỉ lệ user hỏi lại câu tương tự, độ dài câu trả lời bất thường).

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được:

- `trace_id`: `a6bdaf8ea7ec89101fb3f1645a3b3cfa`
- Tổng thời gian: `1704.9 ms` (`1.7s` trên Jaeger UI)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (~`1684 ms`, chiếm **~98.8%** tổng thời gian; span `agent.retrieve_context` chỉ mất `20.7 ms`)
- Dòng log tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-26T09:19:36.738029+00:00", "level": "INFO", "service": "observable-agent", "instance": "d561b71782b2", "event": "http_request", "trace_id": "a6bdaf8ea7ec89101fb3f1645a3b3cfa", "span_id": "405fb70cb7d2338a", "request_id": "4296c522e5e5", "method": "POST", "route": "/ask", "status": 200, "ms": 1704.9}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

Số liệu `Aggregated` từ `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.81 (`POST /ask`: 59.64) | 190 | 230 (`POST /ask`: 240) | 1700 | 67 / 7857 (0.85%) |
| 3 | 65.70 (`POST /ask`: 59.50) | 190 | 220 (`POST /ask`: 230) | 1700 | 50 / 7844 (0.64%) |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

Scale từ `1` lên `3` instance gần như **không làm tăng RPS** (~`65.8` vs `65.7 req/s`) và `p95` chỉ giảm nhẹ (`230ms` → `220ms`). Nguyên nhân là vì tải tạo ra bởi 100 user Locust (có `wait_time` giữa các request) chỉ ở mức ~`65 req/s`, và bản thân mỗi request chủ yếu là **I/O-bound** (chờ `asyncio.sleep` mô phỏng gọi LLM API ~120–180ms) chứ không bị nghẽn CPU — nên 1 instance FastAPI async đã dư sức gánh hết lượng tải này. Khi lưu lượng vượt ngưỡng chịu tải của 1 worker hoặc có tác vụ CPU-bound nặng hơn, scale ngang mới thể hiện rõ sự cải thiện về RPS và p95.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Tail latency (`p95`/`p99`) quan trọng hơn `average`:** Một tỉ lệ nhỏ request chậm (`MOCK_SLOW_RATE`) khiến trải nghiệm người dùng tệ đi rõ rệt dù giá trị trung bình vẫn trông bình thường.
  2. **Chỉ số `cost / câu đúng` đánh giá đúng hiệu quả của RAG:** Agent v2 tốn nhiều token hơn v1 nhưng accuracy tăng từ `4.3%` lên `100%`, nên chi phí thực tế cho mỗi câu trả lời đúng rẻ hơn gấp ~11.7 lần.
  3. **3 trụ cột Metrics – Traces – Logs bổ trợ lẫn nhau:** Prometheus/Grafana phát hiện bất thường tổng quan, Jaeger chỉ ra chính xác span gây chậm/lỗi, và `trace_id` giúp truy thẳng tới dòng log JSON chi tiết.
- Nếu đưa agent này lên production thật, sẽ thêm các metric / alert sau:
  - Counter riêng cho **Rate Limit (`429`)** và **Cost Guard (`402`)** để phát hiện spam hoặc user chạm trần ngân sách.
  - Metric theo dõi **Redis latency / connection errors** (phát hiện sớm trước khi `/ready` chuyển `503`).
  - **Time-to-First-Token (TTFT)** nếu dùng streaming và **Eval Accuracy** định kỳ trên tập mẫu để bắt regression chất lượng (thí nghiệm E).
