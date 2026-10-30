# Documentation Standard

> How code is documented in Whiney. Adapted from Navilott_Vision's standard
> (itself trimmed from Real Python's *Documenting Python Code*), with this
> project's examples. `tests/test_docs.py` enforces the parts a machine can check.

---

## Principles

1. **Each layer answers a different question.** File docstring: *where does this fit?* Function docstring: *what is the contract?* Comment: *why is this line like this?* If two layers say the same thing, delete one.
2. **Types live in signatures, not prose.** Every new or changed public function gets type hints, and mypy checks them (`make lint`). Docstrings describe behavior, not types.
3. **Documentation should shrink when code is refactored, not drift.** Don't list what a module contains or how a function works step by step. Those details go stale.
4. **When unsure, cut.** An outdated docstring is worse than a missing one.

---

## File Docstrings

Every module in `src/whiney/` opens with a docstring that explains its role.

| Section      | Answers                                                                 |
|--------------|-------------------------------------------------------------------------|
| Summary      | One line: what this module does for the app.                            |
| Purpose      | Why it exists and which problem it owns. 2–4 sentences.                 |
| Main package | The primary data structure the module produces and what it represents.  |
| Flow         | The ordered stages the module performs, at app level.                   |

Rules:

- The **main package** is named explicitly (e.g., a Doctor `finding`, `installed.json`). A module built around no single output type is a signal to split or merge it.
- The **Flow** matches the order of the code and stays high-level: one line per stage.
- Do **not** list every class or function. The editor already provides that index.
- Target: 8–20 lines. A module that needs more (installer's UI protocol) is fine; a contract is worth the lines.

```python
"""Health checks: turns the player's setup into findings with a fix for each.

Purpose:
    Catches the setups that crash Skyrim or desync multiplayer before the
    player finds out in game. The installer runs the preflight subset before
    installing; the Doctor tab runs everything.

Main package:
    finding: {"level": "OK" | "WARN" | "FAIL", "area", "title", "detail", "fix"}.
    FAIL means the game will crash or the install will fail; WARN is worth a look.

Flow:
    1. Read plugin headers (masters, ESM/ESL flags) straight from the TES4 record.
    2. Build the effective load order the game uses: masters hoisted first.
    3. Check groups: preflight, plugins, SKSE plugins, mods, system.
    4. run_all collects them; report_text formats them.
"""
```

---

## Function Docstrings

### Full form: public functions

```
Summary line.

Purpose:  (optional; only if the summary line isn't enough)
Inputs:   How each parameter changes behavior. Units and ranges, not types.
Outputs:  What the returned value represents.
Side effects: (only if any) Files, registry, processes, network, the GUI, mutation.
```

- **Inputs** describe *effect*: "Later dates win when two packs share a mod." They do not describe type: "str, the date."
- **Always state units and formats** where they're ambiguous: bytes vs. MB, `"1.6.1170.0"` vs. `"1.6.1170"`, lowercase file names vs. as-written, paths relative to what.
- Parameters that are self-explanatory from name + type (`game`, `path`) can be skipped.
- **Side effects** are required when the function writes files, touches the player's game or Vortex folders, starts a process, opens a UAC prompt, or mutates an argument. Omit the line for pure functions.

```python
def check_plugins(game: Path, req: dict) -> list[dict]:
    """Check the player's live load order: files present, masters active and earlier, under the limit.

    Inputs:
        game: The Skyrim folder (the one holding SkyrimSE.exe).
        req: The pack's requirements; unused today, kept so every check group has one signature.

    Outputs:
        Findings in the order the checks run. One OK finding when nothing is wrong;
        a Sync finding only when the build carries the pack's plugins.txt.
    """
```

### Short form: private helpers and trivial functions

A single summary line, or nothing if the name says it all.

```python
def _levels(findings, area=None):
    return [(f["level"], f["title"]) for f in findings if area is None or f["area"] == area]

def nice_mod_name(folder_name: str) -> str:
    """'Skyrim Souls RE - Unpaused Menus 27859 3.2.0 2026-09-25T11-22Z IoFl' -> 'Skyrim Souls RE - Unpaused Menus'."""
```

**Rule of thumb:** if the docstring would be longer than the function body and the function is private, use the short form.

---

## Classes

- Class docstring: one-line purpose, plus any **invariants** (e.g., "`active` is True only while the watch thread is alive").
- Document only attributes whose meaning, units or format isn't obvious, with a trailing comment.
- Do not list methods or attributes wholesale.

---

## Inline Comments

Comments explain **why**, never **what**. Priority targets:

1. **Tuned constants.** Where did the value come from and what is it sensitive to?
2. **File-format facts.** Byte offsets, flags, the quirks of plugins.txt, Crash Logger's layout, Vortex's folder names.
3. **Workarounds.** Windows, Drive, Vortex or PyInstaller behavior being worked around.

```python
# Good: provenance and consequence
FULL_PLUGIN_LIMIT = 254           # one-byte load order index; 0xFE is light plugins, 0xFF runtime forms

# Good: a format fact the reader can't see
if typ == b"XXXX":                # next field is bigger than 64 KB

# Bad: restates the code
count += 1                        # increment count
```

Delete:

- Comments that restate the line below them.
- Section-banner comments inside short functions. If a function needs banners, it needs splitting. (Banners *between* groups of functions in a long module are fine: `# ---- plugin header reader ----`.)
- Commented-out code. Git has it.
- Change-history comments (`# fixed 9/12`). Git has it.

---

## Tests

pytest prints the test name on failure, so **the name is the docstring**. It states the behavior under test: `test_plugin_loading_before_its_master_fails`, not `test_plugins_2`.

- **Module docstring:** first line `test_<x>.py  --  <what it tests>`; then why that contract matters; then one line per mode (`--software  ...`, `--live  ...`) saying what it runs on. No Main package or Flow.
- **Test functions:** no docstring. If the name can't carry the behavior, rename the test or split it.
- **Fakes, builders and fixtures:** one line saying what they stand in for or produce.
- **Comments** answer only:
  1. *Why the contract matters*: what breaks for a player if this test fails.
  2. *Why the setup is shaped this way*: a fixture built to expose the behavior.
  3. *Where an expected value comes from*: the arithmetic (`# frames 1 and 3 -> (10-1) + (10-3) = 16`), the spec (`# RFC 6598`), and every threshold.

```python
# Good: says what depends on the contract
def test_sync_code_ignores_case_and_disabled_plugins_but_not_order(tmp_path):
    # Players compare codes before multiplayer: same enabled list in the same
    # order must match, and any reorder must not, or desyncs go unnoticed

# Bad: restates the name
def test_header_of_a_missing_file_is_none(tmp_path):
    # checks that a missing file gives None
```

---

## Checklist (per file)

- [ ] Module docstring has Summary, Purpose, Main package, Flow; no symbol inventory
- [ ] New or changed public functions: type hints + Inputs/Outputs describing effect, units, formats
- [ ] Side effects stated where files, processes, registry or the GUI are touched
- [ ] Private helpers: one line or none
- [ ] Every magic number has a provenance comment or is a named constant
- [ ] No what-comments, banners inside functions, dead code, or history comments

**Test files** replace the first two items with:

- [ ] Module docstring names the target and what each mode covers
- [ ] Test names state the behavior; no test docstrings
- [ ] Fakes/builders have a one-line docstring
- [ ] Every expected value, tolerance and threshold has its source in a comment
