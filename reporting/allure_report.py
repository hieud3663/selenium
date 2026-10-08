"""Bridge unittest result events to the official Allure Python SDK."""
import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

import allure_commons
from allure_commons.lifecycle import AllureLifecycle
from allure_commons.logger import AllureFileLogger
from allure_commons.model2 import Label, Parameter, Status, StatusDetails
from allure_commons.types import AttachmentType
from allure_commons.utils import now, uuid4


STATUS_MAP = {"PASS": Status.PASSED, "PARTIAL_PASS": Status.PASSED,
              "FAIL": Status.FAILED, "ERROR": Status.BROKEN, "SKIP": Status.SKIPPED}
SEVERITY_MAP = {"Critical": "blocker", "High": "critical", "Medium": "normal", "Low": "minor"}


class AllureWriter:
    def __init__(self, output):
        self.output = Path(output)
        self.lifecycle = AllureLifecycle()
        self.logger = AllureFileLogger(self.output, clean=False)
        self.uuids = {}

    def __enter__(self):
        allure_commons.plugin_manager.register(self.logger)
        return self

    def __exit__(self, *args):
        allure_commons.plugin_manager.unregister(plugin=self.logger)

    def start(self, test, spec):
        uuid = uuid4()
        self.uuids[id(test)] = uuid
        full_name = test.id()
        scope = spec["automation"]
        with self.lifecycle.schedule_test_case(uuid=uuid) as result:
            result.name = f"{spec['id']}: {spec['title']}" + (" [Partial]" if scope == "Partial" else "")
            result.fullName = full_name
            result.testCaseId = sha256(full_name.encode()).hexdigest()
            result.historyId = result.testCaseId
            result.start = now()
            result.stage = "running"
            result.description = (
                f"Tiền điều kiện: {spec['preconditions']}\n\n"
                f"Bước đặc tả (không phải log thực thi):\n{spec['steps']}\n\n"
                f"Kết quả mong đợi: {spec['expected']}\n\n"
                f"Phạm vi: {scope}\nĐã triển khai: {spec['automated_checks']}\n"
                f"Còn lại: {spec['manual_checks']}"
            )
            result.labels.extend([
                Label(name="parentSuite", value="UTC Browser Tests"),
                Label(name="suite", value=spec["module"]),
                Label(name="subSuite", value=spec["type"]),
                Label(name="framework", value="unittest"),
                Label(name="language", value="python"),
                Label(name="package", value="tests.test_login"),
                Label(name="testClass", value=test.__class__.__name__),
                Label(name="testMethod", value=test._testMethodName),
                Label(name="severity", value=SEVERITY_MAP.get(spec["severity"], "normal")),
                Label(name="tag", value=scope),
                Label(name="tag", value=spec["priority"]),
            ])
            result.parameters.append(Parameter(name="Automation scope", value=scope, excluded=True))

    def finish(self, test, record, redact):
        uuid = self.uuids.pop(id(test))
        with self.lifecycle.update_test_case(uuid=uuid) as result:
            result.stop = now()
            result.stage = "finished"
            result.status = STATUS_MAP[record["status"]]
            detail = redact(record.get("detail", ""))
            result.statusDetails = StatusDetails(message=detail.splitlines()[0] if detail else "",
                                                 trace=detail)
        self.lifecycle.attach_data(uuid4(), redact(json.dumps(record, ensure_ascii=False, indent=2)),
                                   name="Execution result and coverage", attachment_type=AttachmentType.JSON,
                                   parent_uuid=uuid)
        screenshot = record.get("screenshot")
        if screenshot:
            self.lifecycle.attach_file(uuid4(), screenshot, name="Screenshot at failure",
                                       attachment_type=AttachmentType.PNG, parent_uuid=uuid)
        self.lifecycle.write_test_case(uuid=uuid)

    def environment(self, values):
        # ASCII escapes are required by Java .properties; credentials are never included.
        def escape(value):
            text = str(value).replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
            return text.encode("ascii", errors="backslashreplace").decode("ascii")
        (self.output / "environment.properties").write_text(
            "\n".join(f"{key}={escape(value)}" for key, value in values.items()) + "\n", encoding="ascii")


def resolve_command(command="allure"):
    if not command:
        command = "allure"
    expanded = str(Path(command).expanduser())
    if Path(expanded).is_file():
        return str(Path(expanded).resolve())
    found = shutil.which(expanded)
    if found:
        return found
    if command in ("allure", "allure.bat", "allure.cmd"):
        home = Path.home()
        candidates = [
            *home.glob("AppData/Local/Programs/Allure/**/allure.bat"),
            *home.glob("scoop/apps/allure/**/bin/allure.cmd"),
            *Path("C:/Program Files/Allure").glob("**/bin/allure.bat"),
            Path("C:/ProgramData/chocolatey/bin/allure.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve())
    raise RuntimeError("Allure CLI not found. Edit allure_command in config.py to point to its standalone launcher.")


def generate_html(results_dir, output_dir, command="allure"):
    executable = resolve_command(command)
    completed = subprocess.run(
        [executable, "generate", str(results_dir), "-o", str(output_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode:
        raise RuntimeError(f"Allure CLI failed (exit {completed.returncode}): {completed.stderr.strip()}")


def open_html(report_dir, command="allure"):
    report_dir = Path(report_dir)
    if not (report_dir / "index.html").is_file():
        raise RuntimeError("Chưa có HTML report. Chạy run_tests.py --allure-html trước.")
    executable = resolve_command(command)
    subprocess.run([executable, "open", str(report_dir), "--host", "127.0.0.1"], check=True)
