"""Select the CI browser scope from Excel and retain the existing runner's verdict."""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from config import ROOT
from run_tests import main as run_tests
from testcases.reader import auth_flow_ids, load_cases, validate_mapping


def selected_ids(cases, security=True):
    return auth_flow_ids(cases)


def report_errors(report, ids, report_dir):
    errors = []
    if not ids or set(report['results']) != set(ids) or report['tests_run'] != len(ids):
        errors.append('Kết quả không có đủ đúng các testcase đã chọn.')
    if not report['environment']['browser_enabled']:
        errors.append('Browser chưa được bật.')
    if any(record['status'] not in {'PASS', 'PARTIAL_PASS'} for record in report['results'].values()):
        errors.append('Có testcase FAIL, ERROR hoặc SKIP.')
    if not (report_dir / 'allure-report' / 'index.html').is_file():
        errors.append('Thiếu Allure HTML.')
    if not (report_dir / 'results.xlsx').is_file():
        errors.append('Thiếu Excel kết quả.')
    if len(list((report_dir / 'allure-results').glob('*-result.json'))) != len(ids):
        errors.append('Số kết quả Allure không khớp số testcase đã chọn.')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--security', action='store_true', help='Tương thích lệnh cũ; bộ auth đã gồm SQLi/XSS.')
    parser.add_argument('--headless', action='store_true', help='Chạy Chrome headless.')
    args = parser.parse_args(argv)
    cases = load_cases()
    validate_mapping(cases)
    ids = selected_ids(cases)
    if not ids:
        parser.error('Không có testcase browser để chạy.')
    runner_args = ['--browser']
    if args.headless:
        runner_args.append('--headless')
    for case_id in ids:
        runner_args.extend(['--test', case_id])

    previous = set((ROOT / 'reports').glob('*/results.json'))
    exit_code = run_tests(runner_args)
    created = set((ROOT / 'reports').glob('*/results.json')) - previous
    if len(created) != 1:
        print('CI: không tìm thấy đúng một results.json của lượt chạy mới.', file=sys.stderr)
        return exit_code or 1
    report_path = created.pop()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    errors = report_errors(report, ids, report_path.parent)
    counts = Counter(record['status'] for record in report['results'].values())
    lines = [
        '## Kiểm thử đăng nhập UTC', '',
        f"Run ID: `{report['run_id']}`", '',
        f"Chrome: {'headless' if report['environment']['headless'] else 'có giao diện'}; "
        'phạm vi: luồng auth không cần đăng nhập thành công, gồm mẫu SQLi/XSS.', '',
        '| Trạng thái | Số testcase |', '| --- | ---: |',
        *[f'| {status} | {counts[status]} |' for status in ('PASS', 'PARTIAL_PASS', 'FAIL', 'ERROR', 'SKIP')],
        '', f'Đã chọn {len(ids)}/{len(cases)} đặc tả; '
        f"{len(report['unexecuted_cases'])} testcase chưa thực thi.", '',
        'PARTIAL_PASS chỉ xác nhận phần assertion đã triển khai; xem Coverage trong results.xlsx.',
        'Tải artifact utc-browser của run này để xem JSON, Excel, ảnh lỗi và Allure HTML.',
        *(['', *errors] if errors else []),
        '',
    ]
    summary = '\n'.join(lines)
    (report_path.parent / 'ci-summary.md').write_text(summary, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as output:
            output.write(summary)
    print(summary)
    return exit_code or report.get('exit_code', 1) or (1 if errors else 0)


if __name__ == '__main__':
    sys.exit(main())
