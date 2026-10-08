# Kiểm thử luồng auth UTC

**Một lệnh chạy đủ 40 testcase bằng Chrome có cửa sổ, bao gồm SQLi/XSS và sinh Allure HTML:**

```powershell
cd D:\KiemThuPhanMem\selenium
.\.venv\Scripts\python.exe run_tests.py
```

Nếu đã kích hoạt `.venv`, dùng `python run_tests.py`. Không cần `--browser`, `--security` hoặc `--allure-html`; các cờ cũ chỉ được giữ để tương thích. CI dùng `python ci_tests.py` và cùng bộ 40 case.

## Phạm vi 40 testcase

Bộ hiện tại tập trung auth **chưa đăng nhập**. Không testcase nào cần login thành công, tạo phiên đã xác thực, replay token/logout, tài khoản Unicode hợp lệ hay chính sách lockout của tài khoản thật.

- 12 Functional: dữ liệu sai/rỗng, checkbox trước submit, Enter, mở trang và refresh sau lỗi.
- 5 Data Handling: khoảng trắng, độ dài mẫu và dữ liệu Unicode sai.
- 12 Security Samples: masking, các mẫu SQLi ở username/password, XSS, lặp submit sai, HTTPS, POST và iframe trang login.
- 6 Performance/Network: page-load/TTFB nhiều mẫu, latency phản hồi từ chối, bytes/request count và offline/retry.
- 5 UI: controls, Enter với password rỗng, TAB, thông báo chung/status và viewport.

Excel có đúng 40 dòng đặc tả, code có đúng 40 phương thức cùng ID. Phạm vi cũ (gồm happy path, logout, persistence, blind SQLi, lockout và SLA toàn hệ thống) đã được thay theo yêu cầu auth không cần thành công. Không coi các test mẫu này là chứng nhận không có SQLi/XSS hoặc hệ thống có lockout. Ví dụ SEC_09 xác nhận 5 phản hồi sai ở username không tồn tại, không kiểm tra cơ chế khóa tài khoản thật.

Ngân sách 2s/3MiB/50 requests và các độ dài mẫu 1/255/256 nằm trong Excel, là tiêu chí của bài test này, không phải yêu cầu UTC đã được xác nhận. Ngưỡng page-load/TTFB đang giữ theo config người dùng. Testcase khác nhau có thể dùng chung helper khi cùng thao tác và oracle; payload và input field của từng case được ghi cụ thể.

## Cấu trúc

```text
selenium/
├── config.py               # URL và dữ liệu auth trực tiếp trong code
├── run_tests.py            # Runner cục bộ, mặc định chạy cả 40 và sinh HTML
├── ci_tests.py             # Kiểm tra kết quả/artifact khi chạy CI
├── requirements.txt
├── README.md
├── commit.md
├── pages/                  # Locator, thao tác browser và network observations
├── tests/
│   ├── test_login.py       # 40 automation testcase website
│   └── unit/              # Regression của reader, assertion, runner và report
├── testcases/
│   ├── TestCases_VanPhongDienTu_UTC.xlsx
│   ├── reader.py
│   └── AUDIT_40_TESTCASES.md
├── reporting/              # JSON/Excel/Allure results
└── .github/workflows/browser-tests.yml
```

`reports/<run-id>/` là output, không commit. Demo LMS ở `../examples/lms_windows.py`, ngoài suite auth. Project không dùng `.env` hoặc npm/Node.js.

## Chuẩn bị

Python 3.10+, Chrome; Allure CLI 2 cài riêng và Java để sinh HTML.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Giữ/cập nhật trực tiếp trong `config.py`: URL, username đã biết, nonexistent_username, invalid_password, error selector/text, checkbox, timeout và chế độ hiển thị. Các trường success/password gốc còn trong config tương thích lịch sử, nhưng suite không dùng chúng để login thành công. Không cần khai báo cookie/token, logout hoặc ngưỡng lockout.

Allure CLI được tìm trên PATH hoặc thư mục cài mặc định; có thể điền `allure_command` bằng đường dẫn đầy đủ tới `allure.bat`. Không cần package.json hay node_modules.

## Excel và code

Chỉnh sheet **Testcases**, giữ 40 ID/header. Cột Parameters là JSON trong một ô Excel cho dữ liệu riêng của test: payload, lengths, samples, budgets, viewport và thông báo lỗi cụ thể cho trường rỗng. Không có file JSON trung gian. Status đặc tả giữ Not Run, Actual trống; kết quả chạy lưu riêng.

```powershell
.\.venv\Scripts\python.exe run_tests.py --check
```

Reader kiểm tra ID, tham số và ánh xạ phương thức; runner không ghi đè Excel nguồn. Thay đổi expected result bằng chữ không tự sửa assertion Python. Sheet Coverage đã đồng bộ đủ 40 phương thức; khi chỉnh testcase cần cập nhật Coverage nếu sử dụng sheet tham chiếu đó.

## Chạy riêng hoặc CI

```powershell
# Chỉ một case, vẫn sinh HTML:
.\.venv\Scripts\python.exe run_tests.py --test TC_FUNC_02
# Chủ động chọn không có cửa sổ:
.\.venv\Scripts\python.exe run_tests.py --headless
# Regression cục bộ không kết nối UTC:
.\.venv\Scripts\python.exe -m unittest discover -s tests/unit -v
```

Runner mở một Chrome cho cả suite và chỉ đóng khi suite kết thúc. Trước từng testcase, code dừng lượt tải cũ, dọn cookie/storage, đóng tab phụ và khôi phục mạng/viewport/chính sách cache, rồi điều hướng về auth. Không xóa toàn bộ HTTP cache ở mọi case; các testcase cold-cache thực hiện thao tác đó riêng. Chrome chờ DOMContentLoaded (`eager`), sau đó Page Object chờ controls của form. Không có skip do security chưa bật. Dữ liệu/config thiếu báo ERROR; hành vi không đạt assertion báo FAIL. Suite tiếp tục ghi kết quả riêng của từng case. CI chạy Chrome/Xvfb, luôn upload artifact kể cả khi test lỗi.

## Xem HTML

Sau lệnh chạy test, runner in đường dẫn report. Mở bản HTML mới nhất bằng:

```powershell
.\.venv\Scripts\python.exe run_tests.py --open-report
# Hoặc chọn đúng run:
.\.venv\Scripts\python.exe run_tests.py --open-report RUN_ID
```

Lệnh này chỉ mở report, không chạy test. Allure phục vụ bằng local web server; giữ terminal đang chạy và Ctrl+C khi xem xong. Với report nhiều file mặc định, dùng Allure open thay vì mở index.html bằng file://.

Output gồm `results.json`, `results.xlsx` (Execution/Coverage đủ 40 ID), `allure-results`, screenshot lỗi nếu chụp được và `allure-report/index.html`. Allure sinh HTML cả khi test fail/error; nếu CLI lỗi, dữ liệu thô vẫn giữ và exit code là 1.

Exit code: 0 khi các testcase được chọn đạt; 1 khi FAIL/ERROR hoặc lỗi HTML; 2 nếu test framework phát sinh Skip/không có test. PASS chỉ xác nhận expected result trong phạm vi testcase đã mô tả, không chứng nhận an toàn toàn website. Báo cáo che dữ liệu auth trong traceback và xóa input trước khi chụp screenshot.

## Tài liệu

- [Python unittest](https://docs.python.org/3.11/library/unittest.html)
- [Selenium Page Objects](https://www.selenium.dev/documentation/test_practices/encouraged/page_object_models/)
- [OWASP WSTG](https://wstg.owasp.org/v4.2/4-Web_Application_Security_Testing/)
- [Allure generate](https://allurereport.org/docs/v2/generate-report/)
- [Allure view](https://allurereport.org/docs/v2/view-report/)
