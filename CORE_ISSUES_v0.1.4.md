# Kỷ yếu Đánh giá Kỹ thuật & 4 Vấn đề Cốt lõi cần xử lý (v0.1.4)

Tài liệu này ghi nhận chi tiết bản đánh giá kỹ thuật (code review) của phiên bản **Runprint 0.1.3** và kế hoạch hành động cụ thể để khắc phục 4 lỗ hổng cốt lõi trước khi phát hành **v0.1.4**.

---

## I. Tổng quan Đánh giá Runprint v0.1.3

### 1. Định vị & Điểm mạnh cốt lõi
* **Thesis sản phẩm đúng đắn:** *"Git tells you what code you have. Runprint tells you exactly what state produced a result."* (Tập trung vào *Execution Provenance* trước khi làm *Orchestration / Platform*).
* **Local-first & Minh bạch:** Thư mục `.qr/` và filesystem là *Source of Truth*, SQLite chỉ là *Rebuildable Index*. Công cụ không ép buộc người dùng phụ thuộc vào server hay tài khoản đám mây.
* **Nguyên tắc thiết kế:** `CLI = Core`, `SDK = Optional Enrichment`. Người dùng không viết dòng code Python nào vẫn nhận được 70–80% giá trị cốt lõi của công cụ.
* **Tính năng thực chất:** `qr diff`, `qr doctor`, `qr rerun --isolated` (Git worktree riêng biệt), phân cấp Parent/Child lineage.

### 2. Điểm hạn chế hiện tại
Phiên bản 0.1.3 vẫn đang ở giai đoạn Alpha và tồn tại 4 vấn đề kỹ thuật khiến tính năng tái lập (reproducibility) chưa đạt mức tin cậy tuyệt đối cho môi trường nghiên cứu thực tế.

---

## II. Chi tiết 4 Vấn đề Kỹ thuật Trọng yếu

### 🚨 Vấn đề 1: Untracked files chưa được snapshot thực sự vào `git.diff`
* **Hiện trạng:**
  * Module `src/qr/snapshot/git.py` dùng `git status --porcelain` nên phát hiện được file mới tạo (untracked `?? new_file.py`).
  * Tuy nhiên, patch lại được tạo bằng lệnh `git diff --binary HEAD`. Lệnh này của Git theo mặc định **hoàn toàn bỏ qua** các file chưa được track.
* **Hậu quả:**
  * Giả sử người dùng tạo file `new_model.py` (chưa `git add`) và chạy `qr run -- python train.py` (trong đó có `from new_model import Model`).
  * Manifest ghi nhận `dirty: yes`, `modified_files: ["new_model.py"]`, nhưng nội dung code của `new_model.py` không hề có trong `git.diff`.
  * Khi người dùng chạy `qr rerun <run_id> --isolated`, worktree mới được dựng lên từ commit Git và áp patch `git.diff` nhưng **thiếu hoàn toàn file `new_model.py`** → crash `ModuleNotFoundError`!
* **Giải pháp cho 0.1.4:**
  1. Sử dụng kỹ thuật `git add -N <file>` (`--intent-to-add`) cho các file untracked hợp lệ trước khi diff. Khi đó, `git diff --binary HEAD` sẽ tự động sinh patch tạo mới file đầy đủ (`--- /dev/null +++ b/new_file.py`). Sau khi diff xong, tự động gọi `git reset` để hoàn trả index của người dùng về nguyên trạng.
  2. Bổ sung cơ chế **`.qrignore`** và giới hạn dung lượng file text/source (< 5MB) để tự động bỏ qua các file dữ liệu lớn (`.csv`, `.parquet`) hoặc model checkpoint (`.pt`, `.bin`, `.safetensors`) chưa commit.
  3. Ghi nhận danh sách file untracked bị bỏ qua vào `GitSnapshot.untracked_ignored`.

---

### 🚨 Vấn đề 2: `qr rerun` chưa thực sự xác thực và đối chiếu môi trường (Environment Drift)
* **Hiện trạng:**
  * Hệ thống có chụp lại `pip-freeze.txt` trong thư mục `environment/`.
  * Tuy nhiên, preflight của `qr rerun` trong `src/qr/rerun.py` chỉ làm một việc đơn sơ: `lock_path.exists()` (chỉ kiểm tra file có tồn tại trên đĩa hay không).
  * Hệ thống hoàn toàn không đối chiếu xem các package cài đặt trong môi trường hiện tại có khớp với snapshot hay không.
* **Hậu quả:**
  * Nếu 6 tháng sau, người dùng chạy `qr rerun`, môi trường hiện tại đã nâng cấp `numpy` từ 1.24 lên 2.1 hoặc `torch` từ 2.1 lên 2.6 có breaking change, lệnh rerun vẫn chạy và crash, làm mất đi ý nghĩa của provenance.
* **Giải pháp cho 0.1.4:**
  1. Xây dựng module so sánh phiên bản package giữa môi trường hiện tại (`current pip freeze`) và file snapshot (`pip-freeze.txt`).
  2. Tích hợp kiểm tra tự động vào `qr rerun` (cảnh báo rủi ro Low / Medium / High khi phát hiện lệch phiên bản các thư viện lõi: `torch`, `scikit-learn`, `transformers`, `numpy`...).
  3. Bổ sung lệnh CLI mới:
     ```bash
     qr env diff <run_id>
     ```
     In bảng so sánh trực quan phiên bản package giữa máy hiện tại và run cũ.

---

### 🚨 Vấn đề 3: Bắt biến môi trường bằng Denylist tiềm ẩn nguy cơ rò rỉ Credential
* **Hiện trạng:**
  * Trong `src/qr/snapshot/runtime.py`, hệ thống dùng danh sách đen (Denylist) lọc các từ khóa như `SECRET, TOKEN, PASSWORD, KEY, AUTH`.
  * Bất kỳ biến môi trường nào không chứa các từ khóa này đều bị lưu vào `manifest.json`.
* **Hậu quả:**
  * Rất nhiều biến nhạy cảm trong thực tế không nằm trong denylist: `DATABASE_URL=postgres://user:password@host`, `HF_ACCESS=...`, `WANDB_SESSION=...`, `COOKIE=...`, `AWS_SESSION_TOKEN=...`.
  * Toàn bộ secret này sẽ bị lưu dưới dạng **plain text** vào file `manifest.json`. Khi người dùng chia sẻ thư mục `.qr` hoặc commit lên repository, credentials sẽ bị lộ hoàn toàn.
* **Giải pháp cho 0.1.4:**
  1. **Đảo ngược tư duy sang Default Allowlist:** Mặc định **KHÔNG bắt bất kỳ biến môi trường tự do nào**, chỉ bắt danh sách các biến an toàn ảnh hưởng đến tính tất định của ML:
     ```python
     SAFE_REPRODUCIBILITY_ENV_VARS = {
         "CUDA_VISIBLE_DEVICES",
         "OMP_NUM_THREADS",
         "PYTHONHASHSEED",
         "CUBLAS_WORKSPACE_CONFIG",
         "TOKENIZERS_PARALLELISM",
         "MKL_NUM_THREADS",
         "TF_DETERMINISTIC_OPS",
         "TF_CUDNN_DETERMINISTIC",
     }
     ```
  2. Cho phép người dùng tùy chọn khai báo thêm biến cần theo dõi trong `project.json` (`"capture_env": ["EXPERIMENT_PHASE"]`), đồng thời vẫn quét qua bộ lọc `is_sensitive_key` để chống sơ suất.

---

### 🚨 Vấn đề 4: Nhãn `RESTORABLE: LIKELY` đang quá hào phóng và thiếu căn cứ
* **Hiện trạng:**
  * Trong `src/qr/cli.py`, logic xác định mức độ tái lập hiện tại chỉ vỏn vẹn 2 dòng:
    `has_lock = bool(manifest.runtime.packages_lock) -> LIKELY if has_lock else PARTIAL`.
* **Hậu quả:**
  * Có file `pip-freeze.txt` không đồng nghĩa với việc môi trường có thể tái lập được.
  * Một thí nghiệm sử dụng gói cài đặt dạng editable (`pip install -e .`), dùng CUDA extension biên dịch tay, thiếu dataset gốc hoặc sót untracked file... vẫn được gán mác `Restorable: LIKELY` là không trung thực với thực tế.
* **Giải pháp cho 0.1.4:**
  1. Xây dựng **Restorability Scoring Engine (0 - 100 điểm)** với bảng kiểm toán (**Audit Checklist**) dựa trên 3 trụ cột:
     * **Mã nguồn (Source Code - Max 35đ):** Commit Git hợp lệ (+10), git diff đầy đủ không sót file (+15), không có file untracked bị thiếu (+10).
     * **Môi trường (Environment - Max 35đ):** Python version pinned (+10), pip freeze đầy đủ (+15), không có package dạng editable/local path chưa cố định (+10).
     * **Dữ liệu đầu vào (Inputs - Max 30đ):** Dataset URI khai báo (+10), SHA-256 fingerprint khớp với dữ liệu thực tế (+20).
  2. Phân loại minh bạch:
     * `90 - 100`: `HIGHLY_RESTORABLE` (Xanh)
     * `70 - 89`: `PARTIALLY_RESTORABLE` (Vàng)
     * `< 70`: `LOW_RESTORABILITY` (Đỏ)
  3. Cập nhật giao diện `qr show` hiển thị bảng Audit Checklist chi tiết từng tiêu chí.

---

## III. Kế hoạch Hành động cho Bản v0.1.4

| STT | Hạng mục | File cần sửa / tạo mới | Mức độ ưu tiên |
| :--- | :--- | :--- | :--- |
| **1** | Snapshot toàn diện untracked files bằng `git add -N` + `.qrignore` | `src/qr/snapshot/git.py`, `.qrignore` | **Cao nhất (P0)** |
| **2** | Chuyển Environment Capture sang Default Allowlist | `src/qr/snapshot/runtime.py` | **Cao nhất (P0)** |
| **3** | Xây dựng Restorability Scoring Engine & Audit Checklist | `src/qr/scoring.py` (Mới), `src/qr/cli.py` | **Cao (P1)** |
| **4** | Đối chiếu môi trường với `qr rerun --check-env` và `qr env diff` | `src/qr/rerun.py`, `src/qr/cli.py` | **Cao (P1)** |
| **5** | Bộ test case kiểm thử tự động cho 4 tính năng trên | `tests/unit/test_scoring.py`, `test_git_snapshot.py` | **Cao (P1)** |

> **Quyết định chiến lược:** Tạm hoãn Web Dashboard / Cloud UI sang v0.2.0. Tập trung hoàn thiện 100% độ vững chắc của **Core Execution Provenance** cho bản v0.1.4.
