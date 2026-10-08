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
        errors.append('The result set does not exactly match the selected test cases.')
    if not report['environment']['browser_enabled']:
        errors.append('Browser execution was disabled.')
    if any(record['status'] not in {'PASS', 'PARTIAL_PASS'} for record in report['results'].values()):
        errors.append('One or more selected test cases failed, errored, or were skipped.')
    if not (report_dir / 'allure-report' / 'index.html').is_file():
        errors.append('The Allure HTML report is missing.')
    if not (report_dir / 'results.xlsx').is_file():
        errors.append('The Excel results workbook is missing.')
    if len(list((report_dir / 'allure-results').glob('*-result.json'))) != len(ids):
        errors.append('The number of Allure results does not match the selected test cases.')
    return errors


def result_detail(record):
    observations = record.get('observations')
    if observations:
        return json.dumps(observations, ensure_ascii=False, sort_keys=True)
    lines = [line.strip() for line in record.get('detail', '').splitlines() if line.strip()]
    useful = [line for line in lines if not line.startswith(('Traceback ', 'File "', 'During handling'))]
    return useful[-1] if useful else 'No diagnostic detail was recorded.'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--security', action='store_true', help='Compatibility flag; the auth suite already includes SQLi/XSS cases.')
    parser.add_argument('--headless', action='store_true', help='Run Chrome without a graphical display.')
    args = parser.parse_args(argv)
    cases = load_cases()
    validate_mapping(cases)
    ids = selected_ids(cases)
    if not ids:
        parser.error('No browser test cases were selected.')
    runner_args = ['--browser']
    if args.headless:
        runner_args.append('--headless')
    for case_id in ids:
        runner_args.extend(['--test', case_id])

    previous = set((ROOT / 'reports').glob('*/results.json'))
    exit_code = run_tests(runner_args)
    created = set((ROOT / 'reports').glob('*/results.json')) - previous
    if len(created) != 1:
        print('CI: could not find exactly one results.json from the current run.', file=sys.stderr)
        return exit_code or 1
    report_path = created.pop()
    report = json.loads(report_path.read_text(encoding='utf-8'))
    errors = report_errors(report, ids, report_path.parent)
    counts = Counter(record['status'] for record in report['results'].values())
    browser_mode = 'Headless Chrome (no graphical display)' if report['environment']['headless'] else \
        'Headed Chrome on the local display'
    lines = [
        '## UTC authentication browser test results', '',
        f"Run ID: `{report['run_id']}`", '',
        f'Browser mode: {browser_mode}.',
        'Scope: unauthenticated authentication flows, including SQLi/XSS samples.', '',
        '| Status | Test cases |', '| --- | ---: |',
        *[f'| {status} | {counts[status]} |' for status in ('PASS', 'PARTIAL_PASS', 'FAIL', 'ERROR', 'SKIP')],
        '', f'Selected {len(ids)} of {len(cases)} specifications; '
        f"{len(report['unexecuted_cases'])} specifications were not executed.",
        'PARTIAL_PASS covers implemented assertions only. See the Coverage sheet in results.xlsx.',
    ]
    problems = [(case_id, record) for case_id, record in report['results'].items()
                if record['status'] in {'FAIL', 'ERROR', 'SKIP'}]
    if problems:
        lines.extend(['', '### Cases requiring attention', ''])
        lines.extend(f'- `{case_id}` **{record["status"]}**: {result_detail(record)}'
                     for case_id, record in problems)
    security_findings = [
        (case_id, record['observations'])
        for case_id, record in report['results'].items()
        if record.get('observations', {}).get('framing_assessment') == 'SECURITY_FINDING'
    ]
    if security_findings:
        lines.extend(['', '### Security observations', ''])
        lines.extend(
            f'- `{case_id}`: {", ".join(observation["findings"])} '
            f'(X-Frame-Options: {observation["x_frame_options"] or "missing"}; '
            f'CSP frame-ancestors: {"present" if observation["csp_frame_ancestors"] else "missing"}; '
            f'login form rendered in iframe: {observation["login_form_loaded_in_cross_origin_frame"]}).'
            for case_id, observation in security_findings
        )
        lines.append('PASS means the observation was collected. These results do not claim the target is protected.')
    lines.extend(['', 'Download the `utc-browser` artifact for JSON, Excel, screenshots, and the Allure report.'])
    if errors:
        lines.extend(['', '### CI gate', '', '**FAILED**', '', *[f'- {error}' for error in errors]])
    else:
        lines.extend(['', '### CI gate', '', '**PASSED**'])
    lines.append('')
    summary = '\n'.join(lines)
    (report_path.parent / 'ci-summary.md').write_text(summary, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as output:
            output.write(summary)
    print(summary)
    return exit_code or report.get('exit_code', 1) or (1 if errors else 0)


if __name__ == '__main__':
    sys.exit(main())
