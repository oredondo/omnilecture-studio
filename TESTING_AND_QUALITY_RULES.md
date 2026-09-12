# Architecture, Testing, PEP 8, and Security Rules

This document specifies the software engineering, modular architecture, testing, style, and security guidelines for the **OmniLecture Studio** project.

---

## 🏗️ 1. Architecture Guidelines: OOP, Small Files & Code Reuse

1. **Object-Oriented Programming (OOP)**:
   * All modules must follow OOP design principles (classes, encapsulation, clean composition).
   * Avoid monolithic procedures, large functions, or global state mutations.
2. **Small, Single-Purpose Files**:
   * Keep source files small and focused (target **< 150 - 200 lines** per file).
   * Large modules (e.g. GUI windows or orchestration pipelines) must be split into dedicated child packages or components (such as `gui_components/recorder_tab.py`, `gui_components/dialogs.py`).
3. **Code Reuse & Isolated Features**:
   * Always reuse existing classes and utility methods (e.g., `MediaProcessor`, `ZoomDetector`, `DialogUtils`, `LLMManager`, `VideoOCRExtractor`) instead of duplicating code.
   * Add new capabilities as isolated, decoupled modules that compose cleanly with existing services.

---

## 🧪 2. Mandatory Test Execution & Test Creation

1. **Always Run the Complete Test Suite**:
   Whenever any code modification, bug fix, or refactoring is performed, the entire test suite **must** be executed before concluding the task:
   ```bash
   .venv/bin/pytest
   ```
2. **Mandatory Test Coverage for Changes**:
   * Every new feature, module, or change in logic **must** be accompanied by unit tests added to or updated in `test_recorder.py`, `test_pipeline.py`, `test_handwritten_pipeline.py`, or a new `test_*.py` file.
   * Mock external dependencies (e.g. OpenCV, Tesseract, Whisper, LangChain, FFmpeg, D-Bus, GStreamer) appropriately to keep tests fast, reproducible, and isolated.

---

## 🎨 3. PEP 8 Code Quality & Formatting Guidelines

1. **Naming Conventions**:
   * Modules / Files: `snake_case.py`
   * Classes: `CamelCase`
   * Functions / Methods / Variables: `snake_case`
   * Constants: `UPPER_CASE`
2. **Formatting & Structure**:
   * Maximum line length: **120 characters**.
   * Indentation: 4 spaces per level (no tabs).
   * Blank lines: 2 lines before top-level functions and classes; 1 line before methods.
3. **Automated PEP 8 Verification**:
   Run `flake8` to check for style violations, unused imports (`F401`), or syntax issues:
   ```bash
   .venv/bin/flake8 . --exclude=.venv,.temp,__pycache__,pipeline/__pycache__ --max-line-length=120
   ```

---

## 🛡️ 4. Security Analysis with Bandit

1. **Zero High/Medium Severity Security Issues**:
   Run Bandit to detect security risks (hardcoded credentials, unsafe temp file creation, dangerous subprocess executions):
   ```bash
   .venv/bin/bandit -r . -x ./.venv,./.temp,./__pycache__,pipeline/__pycache__ -ll
   ```
2. **Secure Coding Guidelines**:
   * **Subprocess Security**: Avoid `shell=True` when handling external parameters. Pass arguments as a list of strings (`["ffmpeg", "-i", ...]`).
   * **Temporary File Security**: Use `tempfile.gettempdir()` or `tempfile.NamedTemporaryFile` instead of hardcoding `/tmp`.
   * **Secrets Management**: Never commit API keys or passwords. Use `pipeline_config.py` (which is excluded via `.gitignore`) and provide placeholders in `pipeline_config.py.example`.
   * **False Positives**: If a security rule trigger is a verified false positive (e.g., `0o755` permissions for Linux `.desktop` application launchers), mark it with `# nosec <RULE_ID>` and an explanatory comment.

---

## 🚀 Quick Verification Commands

Run all quality and security checks in sequence:

```bash
# 1. Run unit tests
.venv/bin/pytest

# 2. Run static security analysis
.venv/bin/bandit -r . -x ./.venv,./.temp,./__pycache__,pipeline/__pycache__ -ll

# 3. Check PEP 8 code style
.venv/bin/flake8 . --exclude=.venv,.temp,__pycache__,pipeline/__pycache__ --max-line-length=120
```
