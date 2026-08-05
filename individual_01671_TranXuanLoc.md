# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                 |
| --------------- | ---------------------------------------- |
| Họ và tên       | Trần Xuân Lộc                            |
| MSSV            | 2A202601671                              |
| Khóa/Lớp        | K3 / LabAI Day 9                         |
| Vai trò chính   | Lead Architect & Core Multi-Agent Developer |
| Ngày hoàn thành | 2026-08-05                               |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | ----------------- | ---------- |
| Multi-Agent Dispute Pipeline & Business Logic | `src/agents.py`, `src/graph.py`, `src/policy.py`, `src/tools.py`, `src/schemas.py`, `src/logger.py`, `main.py`, `run_pipeline.py`, `verify.py` | 50 file JSON khiếu nại (`input/EC_001.json` - `input/EC_050.json`) và CSV dataset Olist trong `dataset/` | 50 file JSON kết quả (`output/EC_001.json` - `output/EC_050.json`), `logging/trace.jsonl`, `logging/metadata.json`, `architecture.md` | Hoàn thành |
| Verification & Quality Assurance Suite | `verify.py`, `src/schemas.py` | Các file kết quả xử lý trong `output/` và file nhật ký trong `logging/` | Báo cáo kiểm tra 7/7 check validation tự động, exit code 0 | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Tích hợp sơ đồ kiến trúc hệ thống | `architecture.md` / Toàn nhóm | Xây dựng sơ đồ Mermaid và tài liệu kỹ thuật chi tiết về luồng trao đổi dữ liệu 6 Sub-Agents |
| Thiết kế Schema & Audit Logging | `src/schemas.py`, `src/logger.py` | Chuẩn hóa Pydantic schema `DisputeOutput`, định dạng `evidence_ids` regex và cấu trúc `trace.jsonl` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Thiết kế & Thực thi Workflow 6 Agents | `src/graph.py`, `src/agents.py` | Luồng LangGraph điều phối 6 agents (Coordinator -> OrderSeller -> Payment -> Delivery -> Policy -> Verifier) kết hợp Groq LLM (`llama-3.1-8b-instant`) | Chạy `python run_pipeline.py` hoặc `python main.py` |
| Xây dựng Engine Quy tắc EC_POLICY_V1 | `src/policy.py` (`evaluate_policy`) | Thực thi chính xác 6 quy tắc chính sách e-commerce theo thứ tự ưu tiên (Priority 1-6) | Chạy `python verify.py` kiểm tra tính nhất quán tài chính và phân loại |
| Xây dựng Bộ Kiểm định 7 Checks | `verify.py` | Script kiểm tra tự động 7/7 tiêu chuẩn (File Count, Pydantic Schema, Evidence Regex, Array Limits, Financial Precision, Trace Audit, Metadata Audit) | Chạy `python verify.py` trả về exit code 0 |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

- **Bộ kết quả 50 file JSON giải quyết khiếu nại (`output/EC_001.json` - `output/EC_050.json`)** đi kèm nhật ký vết thực thi `logging/trace.jsonl` và file thông số hệ thống `logging/metadata.json`. Bộ dữ liệu này được xác minh 100% khớp Pydantic schema, tròn 2 chữ số thập phân cho mọi tiền tệ BRL, khớp định dạng regex của `evidence_ids` và tuân thủ tuyệt đối quy tắc ưu tiên chính sách `EC_POLICY_V1`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Hệ thống xử lý khiếu nại thương mại điện tử tự động trên tập dữ liệu Brazilian Olist đòi hỏi phối hợp đa tác vụ (tra cứu đơn hàng, đối soát thanh toán, đánh giá trễ giao hàng, áp dụng chính sách hoàn tiền và kiểm định đầu ra). Cần một kiến trúc Multi-Agent mạnh mẽ, có khả năng suy luận bằng LLM kết hợp tính toán chính xác bằng logic Python deterministic, đồng thời ghi vết đầy đủ và vượt qua kiểm định Forensic Audit.

### Cách triển khai

1. **Kiến trúc StateGraph LangGraph (`src/graph.py`)**: Điều phối trạng thái `DisputeState` qua 6 agent node nối tiếp nhau.
   - **CoordinatorAgent**: Tiếp nhận case ID và dữ liệu đầu vào.
   - **OrderSellerAgent**: Gọi tool `get_order_details`, `get_order_items`, `get_order_details` tra cứu CSV và đánh giá bàn giao trễ của người bán.
   - **PaymentAgent**: Gọi tool `get_order_payments` và `reconcile_financials` đối soát tổng tiền thanh toán với tổng tiền hàng + phí vận chuyển (dung sai 0.10 BRL).
   - **DeliveryAgent**: So sánh mốc thời gian giao hàng thực tế `order_delivered_customer_date` với ngày dự kiến `order_estimated_delivery_date` để xác định trách nhiệm (người bán hay đối tác vận chuyển).
   - **PolicyAgent**: Đưa các thông số đã trích xuất vào engine `evaluate_policy` trong `src/policy.py` để áp dụng quy tắc theo ưu tiên 1 đến 6.
   - **VerifierAgent**: Đóng gói payload thành Pydantic model `DisputeOutput` (`src/schemas.py`), kiểm tra ràng buộc số lượng mảng và định dạng regex trước khi ghi output.
2. **Cơ chế Dual-Mode LLM Execution (`src/agents.py`)**: Sử dụng Groq LLM `llama-3.1-8b-instant` cho phần suy luận tóm tắt. Nếu không có API key hoặc gặp lỗi rate-limit, hệ thống tự động fallback sang logic suy luận deterministic mà không gây gián đoạn hay crash pipeline.

### Input, output và contract

| Thành phần | Mô tả |
| ---------- | ------ |
| Input | JSON case trong `input/EC_xxx.json` chứa `case_id`, `customer_request` (hoặc `order_id`) và tập CSV Olist trong `dataset/` |
| Output | File JSON `output/EC_xxx.json` tuân thủ strict schema `DisputeOutput`, file vết `logging/trace.jsonl` và `logging/metadata.json` |
| Module phụ thuộc | `langchain_groq`, `langgraph`, `pydantic`, `pandas` |
| Module sử dụng output | Bộ kiểm định `verify.py` và hệ thống Forensic Audit độc lập |
| Điều kiện lỗi cần xử lý | Trường hợp không có đơn hàng (empty items), thiếu thông tin thanh toán, lỗi rate-limit LLM API, hoặc ngày tháng không đúng định dạng |

### Cách xác minh

```bash
python verify.py
```

- **Kết quả mong đợi:** Tất cả 7/7 checks hiển thị status `[PASS]`, không có lỗi diagnostic log, kết thúc với `OVERALL STATUS: ALL CHECKS PASSED (EXIT CODE 0)`.
- **Kết quả thực tế:** 7/7 checks đã vượt qua xuất sắc, exit code 0.
- **Artifact/log:** File nhật ký trace `logging/trace.jsonl` và thông tin metadata `logging/metadata.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Cần đảm bảo hệ thống Multi-Agent vừa tận dụng được khả năng suy luận linh hoạt của LLM (Groq Llama 3.1 8B), vừa không bao giờ bị dừng đột ngột (crash) do hết quota API rate-limit hoặc lỗi kết nối mạng, đồng thời đảm bảo tính chính xác tuyệt đối 100% của tính toán tài chính và quy tắc chính sách.
- **Các phương án đã cân nhắc:**
  1. *Phương án 1:* Phụ thuộc hoàn toàn vào LLM Tool-Calling cho mọi bước suy luận và tính toán tài chính.
  2. *Phương án 2:* Viết script thuần Python rule-based không sử dụng LLM.
  3. *Phương án 3 (Được chọn):* Kiến trúc Hybrid Dual-Mode — LLM chịu trách nhiệm tạo văn bản giải thích/tóm tắt khi có API Key, còn tính toán số tiền, đối soát tài chính, so sánh mốc thời gian và cây quyết định chính sách `EC_POLICY_V1` do Python deterministic module thực thi.
- **Phương án đã chọn:** Phương án 3 (Kiến trúc Hybrid Dual-Mode).
- **Lý do:** Đảm bảo tính chính xác 100% về tài chính (làm tròn 2 chữ số thập phân, dung sai 0.10 BRL) và tuân thủ thứ tự ưu tiên chính sách, loại bỏ hiện tượng hallucination của LLM khi tính toán số học, đồng thời giúp pipeline đạt độ tin cậy tuyệt đối 100% ngay cả khi mạng chập chờn hoặc API bị giới hạn tần suất.
- **Bằng chứng quyết định phù hợp:** Đã xử lý thành công 50/50 cases trong `input/`, sinh ra 50 file JSON hợp lệ, vượt qua toàn bộ 7/7 kiểm tra trong `verify.py` với 0 lỗi.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Trong quá trình kiểm tra Forensic Audit, các script kiểm tra hoặc module import có thể gây ra side-effect ngoài ý muốn (như tự động tạo/ghi đè dữ liệu vào ổ đĩa khi được import), khiến bộ kiểm tra audit không thể hoạt động ở chế độ "pure read-only" thuần túy.
- **Lệnh hoặc bước tái hiện:** Chạy công cụ kiểm định độc lập hoặc import các module xử lý dữ liệu mà không truyền tham số thực thi.
- **Nguyên nhân gốc:** Một số file script cũ kết hợp cả logic sinh dữ liệu tĩnh và logic kiểm tra vào cùng một luồng thực thi cấp module level (top-level script execution), tự động gọi hàm ghi đĩa ngay khi module được import.
- **Cách xử lý:** Tái cấu trúc (refactor) toàn bộ script kiểm định `verify.py` và các module liên quan thành các lớp/hàm thuần túy (pure read-only auditor verification), di chuyển toàn bộ logic thực thi có tác dụng phụ (side-effects) vào khối lệnh `if __name__ == "__main__":` hoặc các hàm riêng biệt.
- **Cách xác minh sau khi sửa:** Chạy `python verify.py` xác nhận chỉ đọc dữ liệu từ `output/` và `logging/`, không ghi đè hay thay đổi bất kỳ tập tin đầu vào nào, đạt kết quả 7/7 checks PASS.
- **Điều học được:** Luôn tách biệt rõ ràng giữa logic thay đổi trạng thái (state mutation / execution) và logic kiểm định (read-only audit / verification) trong các dự án phần mềm và Multi-Agent pipeline.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của bạn:

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. **Từ Crossref đến Vector Index:** Dữ liệu metadata bài báo (DOIs, tiêu đề, tóm tắt, tác giả) được thu thập từ Crossref API, sau đó qua bước làm sạch và chuẩn hóa văn bản. Tiếp theo, văn bản được chia nhỏ (chunking) thành các đoạn nội dung phù hợp, rồi đưa qua mô hình Embedding (ví dụ `text-embedding-3-small` hoặc `sentence-transformers`) để chuyển đổi thành các vector định danh không gian nhiều chiều. Cuối cùng, các vector này cùng thông tin metadata phụ trợ được lưu trữ và đánh chỉ mục vào Vector Database (như ChromaDB, FAISS, hoặc Qdrant) phục vụ tra cứu tương đồng semantic search.
2. **Đo lường Retrieval/Answer Quality:** Evaluation set tập hợp các câu hỏi thử nghiệm đã kèm sẵn danh sách `ground-truth document IDs` (các tài liệu chuẩn chính xác nhất). 
   - *Đánh giá Retrieval:* So sánh danh sách tài liệu mà hệ thống vector tìm kiếm được với `ground-truth document IDs` thông qua các chỉ số như Recall@K, Precision@K, và MRR.
   - *Đánh giá Answer Quality:* So sánh câu trả lời do LLM sinh ra với câu trả lời chuẩn (ground-truth answer) bằng các thước đo ROUGE, BLEU, BERTScore hoặc đánh giá LLM-as-a-judge (tính trung thực, độ liên quan, độ chính xác).
3. **Quality Checks vs. Freshness Monitoring:**
   - *Quality Checks:* Đánh giá tính toàn vẹn về mặt cấu trúc, tính đúng đắn của dữ liệu (schema validation, chuẩn định dạng regex của evidence ID, độ chính xác tài chính tròn 2 chữ số thập phân, tuân thủ đúng thứ tự ưu tiên chính sách).
   - *Freshness Monitoring:* Theo dõi khía cạnh thời gian và sự biến động dữ liệu theo thời gian (data drift, độ lệch giữa ngày giao hàng thực tế và ngày dự kiến, kiểm tra xem dữ liệu có bị lỗi thời không, độ trễ phản hồi của API).
4. **Sử dụng cùng Test Set cho Baseline, Corrupted và Repaired:** Việc giữ nguyên cùng một test set là nguyên tắc kiểm chứng thực nghiệm bắt buộc nhằm loại bỏ biến số nhiễu từ dữ liệu thử nghiệm. Nhờ đó, bất kỳ sự thay đổi nào về chỉ số hiệu năng (độ chính xác, tỉ lệ thu hồi, mức tuân thủ chính sách) giữa các phiên bản baseline, corrupted và repaired đều phản ánh chính xác tác động của hành vi làm sai lệch dữ liệu (corruption) và hiệu quả thực sự của giải pháp sửa lỗi (repair).
5. **Tiêu chí và Metric đánh giá Repair thành công:** Quá trình Repair được công nhận thành công khi đáp ứng đầy đủ các bằng chứng artifact và metric sau:
   - *Artifact:* 100% 50 file JSON đầu ra sinh ra trong `output/` đạt chuẩn Pydantic schema `DisputeOutput`; file `logging/trace.jsonl` ghi lại đầy đủ luồng thực thi của 6 agents; file `logging/metadata.json` chứa đúng thông tin mô hình Groq Llama 3.1 8B.
   - *Metric:* Bộ kiểm định `verify.py` vượt qua toàn bộ 7/7 kiểm tra (exit code 0); tỷ lệ đối soát tài chính khớp 100% trong dung sai 0.10 BRL; không còn lỗi vi phạm cấu trúc hay định dạng regex.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Trần Xuân Lộc  
**Ngày xác nhận:** 2026-08-05
