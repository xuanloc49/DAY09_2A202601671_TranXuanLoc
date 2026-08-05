# Kiến trúc hệ thống Multi-Agent giải quyết khiếu nại thương mại điện tử

## 1. Tổng quan

Hệ thống sử dụng **6 agent chuyên biệt** được điều phối bởi **LangGraph StateGraph**, xử lý tuần tự 50 case khiếu nại từ dataset Olist (Brazilian E-Commerce). Mỗi agent đảm nhận một domain dữ liệu riêng, sử dụng **LLM Llama 3.1 8B** (qua Groq API) để suy luận và tổng hợp, kết hợp **tool-calling** để tra cứu dữ liệu CSV một cách xác định. Khi không có API Key hoặc LLM gặp lỗi, các agent tự động hoạt động ở chế độ **Deterministic Fallback Mode** đảm bảo tính sẵn sàng cao (fault tolerance).

**Tech stack**: Python · LangChain · LangGraph · Groq API · Pydantic v2 · Pandas

## 2. Sơ đồ luồng xử lý (Pipeline Flow)

```
┌─────────────┐
│   INPUT      │  input/EC_xxx.json
│   (50 case)  │
└──────┬───────┘
       │
       ▼
┌──────────────────┐
│  1. Coordinator  │  Tiếp nhận case, trích xuất claimed_order_id
│     Agent        │  Khởi tạo DisputeState cho pipeline
└──────┬───────────┘
       │  state: { case_id, input_data }
       ▼
┌──────────────────┐     ┌─────────────────────────┐
│  2. Order &      │────▶│  Tool: get_order_details │ Tra cứu orders CSV
│     Seller Agent │────▶│  Tool: get_order_items   │ Tra cứu items CSV
│                  │────▶│  Tool: get_seller_details│ Tra cứu sellers CSV
└──────┬───────────┘     └─────────────────────────┘
       │  state: + order_info { status, items, sellers, carrier_pickup_after_limit }
       ▼
┌──────────────────┐     ┌─────────────────────────┐
│  3. Payment      │────▶│  Tool: get_order_payments│ Tra cứu payments CSV
│     Agent        │────▶│  Func: reconcile_financials│ Đối soát tài chính
└──────┬───────────┘     └─────────────────────────┘
       │  state: + payment_info { payments, payment_total, is_reconciled }
       ▼
┌──────────────────┐     ┌──────────────────────────────┐
│  4. Delivery     │────▶│  Func: check_delivery_lateness│ So sánh ngày giao
│     Agent        │     │  (date-only comparison)       │ vs estimated date
└──────┬───────────┘     └──────────────────────────────┘
       │  state: + delivery_info { is_delivered_after_estimate, responsibility }
       ▼
┌──────────────────┐     ┌─────────────────────────┐
│  5. Policy       │────▶│  Func: evaluate_policy   │ Áp dụng EC_POLICY_V1
│     Agent        │     │  (6 rules, ưu tiên)      │ theo thứ tự ưu tiên
└──────┬───────────┘     └─────────────────────────┘
       │  state: + policy_finding { primary_issue, refund, confidence, ... }
       ▼
┌──────────────────┐     ┌─────────────────────────┐
│  6. Verifier     │────▶│  Pydantic DisputeOutput  │ Validate schema
│     Agent        │────▶│  generate_evidence_ids   │ Tạo evidence IDs
│                  │────▶│  generate_affected_entities│ Tạo entities
└──────┬───────────┘     └─────────────────────────┘
       │  state: + final_output (JSON validated)
       ▼
┌─────────────┐
│   OUTPUT     │  output/EC_xxx.json
│   (50 file)  │
└──────────────┘
```

## 3. Chi tiết từng Agent

### 3.1. Coordinator Agent (`coordinator_agent`)
- **File**: `src/agents.py`
- **Vai trò**: Tiếp nhận case đầu vào, trích xuất `case_id` và `claimed_order_id` từ JSON input
- **Input**: `input_data` (nội dung file EC_xxx.json)
- **Output**: Khởi tạo `DisputeState` với `case_id`, `input_data`
- **LLM**: Không sử dụng (chỉ parsing dữ liệu)

### 3.2. Order & Seller Agent (`order_seller_agent`)
- **File**: `src/agents.py`
- **Vai trò**: Tra cứu thông tin đơn hàng, sản phẩm và seller từ CSV
- **Tool-calling**:
  - `get_order_details(order_id)` → trạng thái đơn, ngày giao, ngày ước tính
  - `get_order_items(order_id)` → danh sách item, giá, freight, shipping_limit_date
  - `get_seller_details(seller_id)` → thông tin seller
- **Logic xác định**: So sánh `order_delivered_carrier_date` > `shipping_limit_date` của từng item để xác định `carrier_pickup_after_limit` và `violating_seller_id`
- **LLM**: Tóm tắt kết quả phân tích đơn hàng (1-2 câu)
- **Output**: `order_info` chứa đầy đủ thông tin đơn, item, seller, cờ vi phạm

### 3.3. Payment Agent (`payment_agent`)
- **File**: `src/agents.py`
- **Vai trò**: Đối soát tài chính — tổng payment vs (item + freight)
- **Tool-calling**:
  - `get_order_payments(order_id)` → danh sách payment rows
  - `reconcile_financials(payment_total, item_total, freight_total)` → kiểm tra khớp trong sai số 0.10 BRL
- **LLM**: Giải thích kết quả đối soát thanh toán
- **Output**: `payment_info` chứa payment_total, payment_count, is_reconciled, discrepancy

### 3.4. Delivery Agent (`delivery_agent`)
- **File**: `src/agents.py`
- **Vai trò**: Đánh giá giao hàng trễ và xác định trách nhiệm
- **Logic xác định**:
  - `check_delivery_lateness()` — so sánh **date-only** (không so timestamp) giữa `order_delivered_customer_date` và `order_estimated_delivery_date`
  - Kết hợp cờ `carrier_pickup_after_limit` từ Order Agent để phân biệt lỗi seller vs logistics
- **LLM**: Tóm tắt đánh giá giao hàng
- **Output**: `delivery_info` chứa `is_delivered_after_estimate`, `delay_responsibility`, `root_cause_code`

### 3.5. Policy Agent (`policy_agent`)
- **File**: `src/agents.py`, `src/policy.py`
- **Vai trò**: Áp dụng bộ quy tắc nghiệp vụ EC_POLICY_V1 theo **thứ tự ưu tiên nghiêm ngặt**
- **Engine**: Hàm `evaluate_policy()` trong `src/policy.py` đánh giá 6 rule tuần tự:

| Ưu tiên | Rule | Điều kiện |
|:---:|---|---|
| 1 | `canceled_order_paid` | status = canceled AND payment > 0 |
| 2 | `unavailable_order_paid` | status = unavailable AND payment > 0 |
| 3 | `late_delivery_seller` | Giao sau estimated AND carrier pickup sau shipping_limit |
| 4 | `late_delivery_logistics` | Giao sau estimated AND carrier pickup không muộn hơn shipping_limit |
| 5 | `valid_split_payment` | ≥2 payment rows AND payment khớp item+freight (±0.10 BRL) |
| 6 | `unsupported_late_claim` | Giao không muộn hơn estimated AND payment khớp |

- **Confidence động**: Tính dựa trên mức độ chênh lệch payment (`_payment_confidence`), số ngày trễ (`_delivery_late_confidence`), số ngày seller vượt limit (`_seller_late_confidence`)
- **LLM**: Giải thích quyết định policy cho case
- **Output**: `policy_finding` chứa primary_issue, root_cause_code, responsible_party, refund, confidence

### 3.6. Verifier Agent (`verifier_agent`)
- **File**: `src/agents.py`
- **Vai trò**: Kiểm chứng và lắp ráp output cuối cùng
- **Logic**:
  - Gọi `generate_evidence_ids()` để tạo evidence (tối đa 10)
  - Gọi `generate_affected_entities()` để tạo entity sets (tối đa 5 mỗi loại)
  - Lọc seller trong evidence: chỉ đưa `seller:<id>` vào `evidence_ids` khi `primary_issue == "late_delivery_seller"` (các seller liên quan vẫn được giữ trong `affected_entities.seller_ids`)
  - Lọc responsible_parties: trả mảng rỗng `[]` khi không có ai chịu trách nhiệm (`responsible_party == "none"`)
  - Validate toàn bộ output qua Pydantic model `DisputeOutput` (kiểm tra evidence ID format, financial rounding, entity count limits, cross-field consistency)
- **LLM**: Không sử dụng (chỉ validation xác định)
- **Output**: `final_output` — JSON hoàn chỉnh sẵn sàng ghi file

## 4. Tầng dữ liệu (Data Layer)

### 4.1. OlistDataManager (Singleton)
- **File**: `src/tools.py`
- **Vai trò**: Load toàn bộ 5 file CSV Olist vào bộ nhớ, index theo khóa chính cho tra cứu O(1)
- **Bảng dữ liệu**:

| CSV File | Index Key | Cấu trúc |
|---|---|---|
| `olist_orders_dataset.csv` | `order_id` | Dict `{order_id: row}` |
| `olist_order_items_dataset.csv` | `order_id` | Dict `{order_id: [items]}` |
| `olist_order_payments_dataset.csv` | `order_id` | Dict `{order_id: [payments]}` |
| `olist_sellers_dataset.csv` | `seller_id` | Dict `{seller_id: row}` |
| `olist_customers_dataset.csv` | `customer_id` | Dict `{customer_id: row}` |

### 4.2. Tool Functions (LangChain @tool)
- `get_order_details(order_id)` — tra cứu trạng thái và ngày tháng
- `get_order_items(order_id)` — tra cứu items, giá, freight, seller, shipping_limit
- `get_order_payments(order_id)` — tra cứu payment rows
- `get_seller_details(seller_id)` — tra cứu thông tin seller

### 4.3. Hàm tính toán xác định
- `check_delivery_lateness()` — so sánh `.date()` (date-only, không so timestamp)
- `check_carrier_pickup_lateness()` — so sánh full timestamp
- `reconcile_financials()` — kiểm tra payment khớp item+freight trong sai số 0.10 BRL

## 5. State Management (LangGraph)

Pipeline sử dụng `DisputeState` (TypedDict) làm shared state:

```python
class DisputeState(TypedDict, total=False):
    case_id: str                              # ID case (EC_001..EC_050)
    input_data: Dict[str, Any]                # Nội dung file input JSON
    order_info: Optional[Dict[str, Any]]      # Kết quả từ Order & Seller Agent
    payment_info: Optional[Dict[str, Any]]    # Kết quả từ Payment Agent
    delivery_info: Optional[Dict[str, Any]]   # Kết quả từ Delivery Agent
    policy_finding: Optional[Dict[str, Any]]  # Kết quả từ Policy Agent
    final_output: Optional[Dict[str, Any]]    # Output cuối từ Verifier Agent
    trace_steps: List[Dict[str, Any]]         # Trace log (append-only)
    errors: List[str]                         # Danh sách lỗi (append-only)
```

Luồng handoff: mỗi agent đọc state từ agent trước và ghi thêm kết quả của mình.

## 6. Schema Validation (Pydantic v2)

- **File**: `src/schemas.py`
- Toàn bộ output được validate qua model `DisputeOutput` với:
  - `Assessment`: primary_issue (6 giá trị hợp lệ), case_status, confidence ∈ [0, 1]
  - `AffectedEntities`: tối đa 5 ID mỗi loại
  - `RootCauseAnalysis`: tối đa 3 ranked_causes, 3 responsible_parties
  - `FinancialResolution`: tự động làm tròn 2 chữ số thập phân
  - `evidence_ids`: tối đa 10, validate regex format
  - Cross-field validation: refund > 0 → `action_required`, refund = 0 → `no_action`

## 7. Logging & Tracing

- **File**: `src/logger.py`
- **trace.jsonl**: Mỗi agent ghi 1 dòng JSON cho mỗi case, bao gồm: timestamp, case_id, agent_name, action, input/output summary, status, latency_ms
- **metadata.json**: Model name (`llama-3.1-8b-instant`), parameter size (`8B`), framework, runtime info
- Thread-safe (dùng `threading.Lock`)

## 8. Batch Processing

- **File**: `run_pipeline.py`, `main.py`
- Đọc 50 file JSON từ `input/`, sắp xếp theo số case
- Gọi `run_dispute_pipeline()` cho từng case tuần tự
- Ghi output JSON vào `output/`
- Hỗ trợ CLI arguments: `--case-id`, `--limit`, `--clear-trace`, `--verbose`
- Cấu hình qua `.env`: `GROQ_API_KEY`, `GROQ_MODEL`, `LLM_TEMPERATURE`, `INPUT_DIR`, `OUTPUT_DIR`

## 9. Cấu trúc thư mục

```
DAY09_2A202601671_TranXuanLoc/
├── main.py                  # Entrypoint chính
├── run_pipeline.py          # Batch processing engine
├── requirements.txt         # Dependencies
├── .env.example             # Template cấu hình
├── .gitignore
├── architecture.md          # Tài liệu kiến trúc (file này)
├── individual_01671_TranXuanLoc.md  # Báo cáo cá nhân
│
├── src/
│   ├── __init__.py
│   ├── agents.py            # 6 agent functions
│   ├── graph.py             # LangGraph StateGraph assembly
│   ├── policy.py            # EC_POLICY_V1 rules engine
│   ├── tools.py             # OlistDataManager + @tool functions
│   ├── schemas.py           # Pydantic v2 schemas
│   └── logger.py            # Execution tracing
│
├── data/                    # 9 CSV files (Olist dataset)
├── input/                   # 50 input cases (EC_001..EC_050)
├── output/                  # 50 output cases (generated)
└── logging/
    ├── trace.jsonl           # Execution trace
    └── metadata.json         # System metadata
```
