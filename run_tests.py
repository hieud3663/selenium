"""Single entry point: validate testcase Excel, run browser checks and create reports."""
import argparse
import platform
import subprocess
import sys
import unittest
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit

from config import ROOT, SETTINGS
from reporting.test_result import EvidenceResult, result_exit_code, save_json, save_results
from testcases.reader import auth_flow_ids, load_cases, validate_mapping


def html_report_path(run_id):
    reports_root = ROOT / "reports"
    if run_id == "latest":
        candidates = list(reports_root.glob("*/allure-report/index.html"))
        if not candidates:
            raise RuntimeError("Chưa có HTML report; chạy với --allure-html trước.")
        return max(candidates, key=lambda path: path.stat().st_mtime).parent
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("--open-report nhận RUN_ID, không nhận đường dẫn.")
    return reports_root / run_id / "allure-report"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chạy luồng auth không cần đăng nhập thành công và xuất báo cáo.")
    parser.add_argument("--check", action="store_true", help="Chỉ kiểm tra Excel và ánh xạ testcase; không chạy browser.")
    parser.add_argument("--browser", action="store_true", help="Bật browser; mặc định đã bật trong config.py.")
    parser.add_argument("--headless", action="store_true", help="Chạy Chrome không có cửa sổ nếu chủ động chọn.")
    parser.add_argument("--test", action="append", dest="test_ids", metavar="TC_ID",
                        help="Chỉ chạy testcase có ID được chọn; có thể lặp tùy chọn.")
    parser.add_argument("--security", action="store_true", help="Tương thích lệnh cũ; bộ auth đã gồm các mẫu SQLi/XSS.")
    parser.add_argument("--allure-html", action="store_true", help="Tương thích lệnh cũ; HTML luôn được sinh.")
    parser.add_argument("--open-report", nargs="?", const="latest", metavar="RUN_ID",
                        help="Mở HTML report có sẵn; mặc định bản HTML mới nhất, không chạy test.")
    args = parser.parse_args(argv)
    if args.open_report:
        from reporting.allure_report import open_html
        try:
            open_html(html_report_path(args.open_report), SETTINGS.allure_command)
        except KeyboardInterrupt:
            return 0
        except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
            print("Không mở được report:", error, file=sys.stderr)
            return 1
        return 0
    cases = load_cases()
    validate_mapping(cases)
    if args.check:
        counts = dict(Counter(case['automation'] for case in cases))
        print(f"Excel hợp lệ: {len(cases)} testcase; phạm vi {counts}.")
        print("Khớp ID/phạm vi với code; đây không phải xác nhận tự động hóa đủ mọi bước hoặc đã Pass trên UTC.")
        return 0
    settings = replace(SETTINGS, run_browser=True,
                       run_security=True,
                       headless=args.headless or SETTINGS.headless)
    from tests.test_login import TestLogin
    from reporting.allure_report import AllureWriter, generate_html
    from selenium import __version__ as selenium_version

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    report_dir = ROOT / "reports" / run_id
    report_dir.mkdir(parents=True)
    if args.test_ids:
        available = set(unittest.defaultTestLoader.getTestCaseNames(TestLogin))
        names = ["test_" + test_id for test_id in dict.fromkeys(args.test_ids)]
        unknown = [name.removeprefix("test_") for name in names if name not in available]
        if unknown:
            parser.error("ID chưa có automation: " + ", ".join(unknown))
        suite = unittest.TestSuite(TestLogin(name) for name in names)
    else:
        names = ["test_" + case_id for case_id in auth_flow_ids(cases)]
        if not names:
            parser.error("Excel không có testcase auth.")
        suite = unittest.TestSuite(TestLogin(name) for name in names)
    specs = {case["id"]: case for case in cases}
    for test in suite:
        test.settings = settings
        test.spec = specs[test._testMethodName.removeprefix("test_")]
    with AllureWriter(report_dir / "allure-results") as allure_writer:
        factory = lambda *a, **kw: EvidenceResult(*a, report_dir=report_dir, cases=cases,
                                                allure_writer=allure_writer, settings=settings, **kw)
        try:
            result = unittest.TextTestRunner(verbosity=2, resultclass=factory).run(suite)
        finally:
            # Also close the shared browser if reporting raises outside unittest's testcase lifecycle.
            TestLogin.doClassCleanups()

    target = urlsplit(settings.url)
    report = {
        "run_id": run_id, "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "tests_run": result.testsRun,
        "counts": dict(Counter(record["status"] for record in result.records.values())),
        "environment": {
            "python": platform.python_version(), "selenium": selenium_version,
            "platform": platform.system(),
            "target_origin": f"{target.scheme}://{target.hostname}:{target.port or (443 if target.scheme == 'https' else 80)}",
            "browser_enabled": settings.run_browser, "security_enabled": settings.run_security,
            "headless": settings.headless,
            "browser_sessions": getattr(TestLogin, "_browser_sessions", None),
        },
        "unexecuted_cases": [case["id"] for case in cases if case["id"] not in result.records],
        "results": result.records, "exit_code": result_exit_code(result),
        "suite_errors": result.suite_errors,
        "scope": "Kết quả của các assertion đã triển khai; không chứng nhận an toàn hoặc SLA toàn hệ thống.",
    }
    save_results(report_dir, cases, report)
    allure_writer.environment(report["environment"] | {"run_id": run_id, "scope": report["scope"]})
    try:
        generate_html(report_dir / "allure-results", report_dir / "allure-report", settings.allure_command)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print("Lỗi sinh Allure HTML:", error, file=sys.stderr)
        report["exit_code"] = 1
        report["allure_html_error"] = result.redact(str(error))
        save_json(report_dir, report)
    print("Kết quả theo testcase:", report["counts"])
    print("Chưa thực thi:", len(report["unexecuted_cases"]))
    print("Báo cáo:", report_dir)
    print("Allure results:", report_dir / "allure-results")
    if "allure_html_error" not in report:
        print("Allure HTML:", report_dir / "allure-report")
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
