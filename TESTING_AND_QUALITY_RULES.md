# Architecture, Testing, PEP 8, and Security Rules

This document specifies the software engineering, modular architecture, testing, style, and security guidelines for the **OmniLecture Studio** repository.

---

## 🏗️ 1. Architecture Guidelines: OOP, Packages & Code Reuse

1. **Object-Oriented Programming (OOP) & SOLID Principles**:
   * All business logic must follow OOP design principles (classes, encapsulation, clean composition, and strategy patterns).
   * Decouple platform-specific backends using abstract base classes (e.g., `BaseAudioBackend` in `recorder/audio_recorder.py`, `BaseInstaller` in `install.py`).
   * Avoid monolithic procedures, global mutable state, or procedural script clutter in the root directory.

2. **Clean Project Package Structure**:
   * **Root directory**: Contains strictly application entry points (`main.py`, `gui.py`, `dictation_gui.py`, `install.py`, `config.py`), project configuration (`pyproject.toml`, `requirements.txt`), and documentation.
   * **`recorder/`**: Screen and audio capture engine (`ZoomDetector`, `DisplayManager`, `VideoRecorder`, `AudioRecorder`, `MediaProcessor`).
   * **`pipeline/`**: AI transcription, OCR, LangGraph orchestration, handwritten digitization, voice dictation, and `pdf_compiler/`.
   * **`gui_components/`**: Modular GTK 3 interface tabs and dialog helpers.
   * **`scripts/`**: Reusable standalone CLI tools (`compress_video.py`, `recover.py`).
   * **`tests/`**: Unit and integration test suite (`tests/test_*.py` and `tests/conftest.py`).

3. **Small, Single-Purpose Files**:
   * Keep source files small and focused (target **< 150 - 200 lines** per file).
   * When a module grows, refactor it into dedicated child packages or modular components.

4. **Code Reuse & Zero Duplication**:
   * **Never duplicate code**: Always reuse existing classes and utility methods (`MediaProcessor`, `ZoomDetector`, `AudioRecorder`, `LLMManager`, `VideoOCRExtractor`).
   * Centralize environment setup and configuration resolving in `config.py`.

---

## 🧪 2. Mandatory Test Execution & Test Creation

1. **Always Run the Complete Test Suite**:
   Whenever any code modification, bug fix, or refactoring is performed, the test suite **must** be executed before concluding the task:
   ```bash
   .venv/bin/pytest tests/
   ```
   Do not conclude any task unless 100% of the tests pass cleanly.

2. **Test Location & Organization**:
   * All test modules must live inside the `tests/` directory (`tests/test_<feature>.py`).
   * Shared test fixtures and platform mocks (PyGObject, D-Bus, Vision, Hardware) belong in `tests/conftest.py`.

3. **Mandatory Test Coverage for Changes**:
   * Every new feature, module, or change in logic **must** be accompanied by unit tests.
   * Mock external hardware dependencies (microphones, audio streams, X11 windows, D-Bus, OCR, external APIs) to keep tests fast, hermetic, and reproducible.

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
   * Group imports at the top: Standard library -> Third-party -> Local modules.

3. **Automated PEP 8 Verification**:
   Verify code style and import cleanliness using `flake8`:
   ```bash
   .venv/bin/flake8 . --exclude=.venv,.temp,__pycache__,pipeline/__pycache__,recorder/__pycache__ --max-line-length=120
   ```

---

## 🛡️ 4. Static Security Analysis (Bandit)

1. **Zero High/Medium Severity Security Issues**:
   Run Bandit to detect security risks:
   ```bash
   .venv/bin/bandit -r . -x ./.venv,./.temp,./__pycache__,pipeline/__pycache__,recorder/__pycache__ -ll
   ```

2. **Secure Coding Guidelines**:
   * **Secrets Management**: Never commit API keys, tokens, or credentials. Use `pipeline_config.py` (excluded via `.gitignore`) or `OMNILECTURE_*` environment variables, and provide safe placeholders in `pipeline_config.py.example`.
   * **Safe Subprocess Calls**: Never pass unescaped user input or concatenated strings with `shell=True`. Always pass argument lists.
   * **File Permissions**: When setting execution permissions (e.g. desktop launchers), annotate intentional permissions with `# nosec B103` accompanied by an explanatory comment.

---

## 📖 5. Documentation Integrity

Whenever you introduce a new feature, change a configuration option, or modify pipeline parameters:
1. Always update [README.md](README.md) with user guides, architecture diagrams, CLI flags, and installation steps.
2. Maintain clear docstrings and logging statements across all public classes and functions.
