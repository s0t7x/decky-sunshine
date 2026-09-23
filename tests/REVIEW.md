# Reviewing this suite

What to look for when the tests, their comments or the configuration around
them are reviewed. Written down because these criteria were arrived at the
expensive way - five review passes over the suite, 124 findings - and
re-deriving them costs that again.

How to use it: pick one part, go through the whole diff against it, then take
the next part. Mixing them produces a pass that finds the obvious things three
times and the subtle ones never.

What this file is *not*: how to run the tests, what the coverage ratchet is,
or how mutation testing is read. That is `tests/README.md`, and it stays the
only copy.

---

## Part 1 - findings in tests

Ordered by weight. T1 to T3 are the ones that produce a **green test for
behaviour that is gone** - the reason the review happened at all.

### T1 - The fake discards the very thing the test's name is about

A stand-in accepts an argument and throws it away, so the test passes whatever
the production code puts there.

```python
monkeypatch.setattr(glob, "glob", lambda pattern: paths)   # pattern ignored
def which(tool, path=None): return None if tool in missing else "/usr/bin/x"
def _run_and_check(self, args, context=None): self.steps.append(args[0])
patch.setattr(asyncio, "sleep", lambda _: real_sleep(0))   # duration dropped
```

Each of those let a real value be changed to anything - the search pattern,
the PATH the tools are looked for on, every argument after the first, the
length of every retry delay - with the suite staying green.

**The rule:** a fake records what it was asked for, and something asserts it.
Recording costs one line; the alternative is an untested argument that looks
tested.

### T2 - The assertion holds for a property the value has anyway

`assert path.startswith("/")` on a path that is built absolute. `assert "'" in
command` on a string that was quoted by the function under test. `assert
decoded == "abc"` where the two encodings agree on ASCII. The assertion is
true before and after the behaviour is removed.

**The rule:** ask what the assertion would look like if the code were wrong. If
the answer is "the same", it is not an assertion.

### T3 - The unit is tested, its assembly is not

`NoRedirect` was tested on its own; that it is installed in the opener
`_request` actually uses was not. The TLS context was tested; that the
controller builds it was not. Both halves pass, the wiring between them is
free to disappear.

**The rule:** for every seam, one test that crosses it. It is usually the only
test in the file that touches the real constructor.

### T4 - A fragment is asserted where the whole value is the behaviour

`assert any("not set or invalid" in line for line in logger.infos)` leaves
everything else in that line untested. For a log message or a piece of UI text
the wording *is* the behaviour - it is what a user pastes into a bug report.

**The rule:** pin the whole line. `message in logger.infos` compares list
elements, so it is exact and no longer to write. Same for the frontend:
`expect(logged).toHaveBeenCalledWith("[SUN]", "Backend method pair failed", error)`.

A changed message then breaks a test. That is the test working, not
brittleness.

### T5 - The construction does not reach the branch the name claims

```python
def test_a_refusal_reported_as_a_plain_oserror_counts_too(api):
    error = OSError(111, "Connection refused")     # ... is a ConnectionRefusedError
```

Python maps errno to a subclass, so the `isinstance(e.reason,
ConnectionRefusedError)` check above caught it and the errno branch the test
was named for never ran. The test passed with that branch deleted.

**The rule:** where a test claims to exercise the second half of an `or`, add
the precondition that says so - `assert type(error) is OSError`.

### T6 - A boundary is pinned comfortably past itself

A stability window checked at 400 ms when it is 300. A retry budget checked at
"far beyond the limit". `>` and `>=` are then interchangeable.

**The rule:** pin the boundary *on* the boundary, and say in the docstring
that this is why the number is exact.

### T7 - An order is pinned that has no reason

A test that asserts call A happens before call B, where nothing depends on it.
It fails on a harmless reordering and teaches the next reader that the order
matters when it does not.

**The rule:** an order assertion carries the reason in its docstring, or it
goes. When the reason is stripped and what remains duplicates another test,
delete the test.

### T8 - Invented input where the real one answers the question

Scripted data is right for a parser's edge cases. It is wrong when the
question is about a specific machine: "does the filesystem hosting the setuid
copy allow setuid" is answered by the Deck's own `/proc/self/mounts` and by
nothing else. The real table also held a stacked mount point that no invented
one would have.

**The rule:** when a test encodes an assumption about the target system, use
that system's data and say in the docstring that it is verbatim.

---

## Part 2 - comments and docstrings

### K1 - Forward-looking

A comment says why the code is as it is, for whoever reads it next. Not what
changed, not which review produced it. No `# P1-10: ...`, no "this used to
be", no "the regression was".

Allowed, because it is a reason rather than a history: a reference to the bug
the code prevents (`#112`, `LizardByte/Sunshine#3944`).

### K2 - Not redundant with the code

No comment that restates the line below it in prose.

### K3 - Not redundant with other comments

One canonical place per subject, a one-line pointer everywhere else. The
coverage ratchet was once explained in five places; it now lives in
`tests/README.md` and is referenced.

### K4 - The claim has to carry

Two ways it fails, both seen:

* overstatement - a fixture docstring claiming a thing was "never wrong"
* a rationale that does not support the decision it is attached to - the
  reason given was true, and was not the reason

### K5 - Placement

The comment sits with the thing it explains, not a field above or below it.

### K6 - Language and register match the surroundings

English, same density and tone as the neighbouring prose. No leftovers in
another language, no ASCII substitutes for accented characters.

### K7 - The name and docstring describe what is actually checked

The docstring side of T5. A test name is a claim; the assertions have to
honour it.

### K8 - References point at something that exists

`see tests/README.md`, `see __init__`, `see test_audio_socket.py` - all still
true after the file moved or the section was renamed.

---

## Part 3 - configuration and CI

### C1 - Trigger completeness

`pull_request` without `types:` does **not** include `labeled`. A workflow
that is meant to react to a label needs it spelled out, or the label is put on
a failed run and nothing happens.

`pull_request` workflows run from the **head branch's** copy of the file, so a
workflow that exists only on the feature branch does run in the PR. `push:
branches: [main]` does not fire for a feature-branch push, and
`workflow_dispatch` only appears in the UI once the file is on the default
branch.

### C2 - Concurrency

`cancel-in-progress` belongs on pull requests, where a new push supersedes the
old run. Not on `main`: there the cancelled run is the only one that commit
will ever get.

### C3 - Least privilege

The default token is far wider than any of these jobs needs. `permissions:
contents: read` unless a job asks for more.

### C4 - The gate is the gate, once

A reporting step that also enforces the threshold turns the override label
into decoration. `coverage report --fail-under=0` when the gate is the step
above it.

### C5 - Path filters against bot commits

The release job commits a version-only bump to `package.json`. A path filter
listing `package.json` makes that commit start a run, which then cancels the
one for the real merge.

### C6 - File modes live in the index

`core.fileMode=false` in this repo, so a script that is executable locally is
not executable for anyone else until `git update-index --chmod=+x`.

---

## Part 4 - mutation results

How to read a surviving mutant, and why `# pragma: no mutate` is the wrong
tool for it, is in `tests/README.md` along with the current list of
equivalents. The only thing to add at review time: **a survivor that is called
equivalent needs its reasoning written down in that list.** An undocumented
"equivalent" is indistinguishable from an unexamined one, and the next reader
pays for it twice.
