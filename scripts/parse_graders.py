"""Step 1 of distill workflow: parse one PB grader into per-test feature jsonl.

Output schema (one line per pytest test function):
{
  "task_id": str,
  "branch": str,
  "test_file": str,           # e.g. "test_basic_invocation.py"
  "test_name": str,           # e.g. "test_no_arguments"
  "docstring": str | null,
  "invocations": [            # all run()/popen() calls inside the test body
    {"call": "run", "args": [...], "kwargs": {...}}
  ],
  "assertions": [             # each `assert <expr>` decomposed
    {"target": "returncode"|"stdout"|"stderr"|"other",
     "op": "eq"|"ne"|"contains"|"not_contains"|"startswith"|"endswith"|"matches"|"truthy"|"other",
     "expected": <literal-or-str-repr>,
     "modifiers": ["lower"|"strip"|...],
     "raw": "<source>"}
  ],
  "unparseable": bool         # true if the function couldn't be analyzed
}
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import tarfile
import tempfile
from pathlib import Path


ASSERT_TARGETS = {"returncode", "stdout", "stderr"}
OP_NAMES = {
    ast.Eq: "eq",
    ast.NotEq: "ne",
    ast.Lt: "lt",
    ast.LtE: "le",
    ast.Gt: "gt",
    ast.GtE: "ge",
    ast.In: "contains",
    ast.NotIn: "not_contains",
    ast.Is: "is",
    ast.IsNot: "is_not",
}


def literal_repr(node: ast.AST) -> str | int | float | bool | None | dict:
    """Best-effort literal extraction. Returns string source repr if not literal."""
    try:
        return ast.literal_eval(node)
    except Exception:
        return {"_expr": ast.unparse(node)}


def find_invocations(fn: ast.FunctionDef) -> list[dict]:
    """Extract calls to run(...) / popen(...) inside the test body."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            fname = None
            if isinstance(node.func, ast.Name):
                fname = node.func.id
            elif isinstance(node.func, ast.Attribute):
                fname = node.func.attr
            if fname in ("run", "popen"):
                args = [literal_repr(a) for a in node.args]
                kwargs = {kw.arg: literal_repr(kw.value) for kw in node.keywords if kw.arg}
                out.append({"call": fname, "args": args, "kwargs": kwargs})
    return out


def analyze_target(node: ast.AST) -> tuple[str, list[str]]:
    """Walk an expression like `result.stderr.lower().strip()` -> ('stderr', ['lower','strip'])."""
    modifiers: list[str] = []
    cur = node
    for _ in range(20):
        if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
            modifiers.append(cur.func.attr)
            cur = cur.func.value
            continue
        if isinstance(cur, ast.Attribute):
            attr = cur.attr
            if attr in ASSERT_TARGETS:
                return attr, list(reversed(modifiers))
            modifiers.append(attr)
            cur = cur.value
            continue
        if isinstance(cur, ast.Name):
            return cur.id, list(reversed(modifiers))
        return "other", list(reversed(modifiers))
    return "other", list(reversed(modifiers))


def split_target_expected(left: ast.AST, right: ast.AST) -> tuple[ast.AST, ast.AST, bool]:
    """Return (target_node, expected_node, swapped). For `b'x' in stderr` the target is right."""
    def looks_like_target(n: ast.AST) -> bool:
        cur = n
        for _ in range(20):
            if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute):
                cur = cur.func.value
                continue
            if isinstance(cur, ast.Attribute):
                cur = cur.value
                continue
            if isinstance(cur, ast.Name):
                return cur.id in ("result", "r", "res", "proc")
            return False
        return False

    if looks_like_target(left):
        return left, right, False
    if looks_like_target(right):
        return right, left, True
    return left, right, False


def parse_assertion(node: ast.Assert) -> dict:
    raw = ast.unparse(node.test)
    test = node.test

    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return {"target": "other", "op": "truthy", "expected": None, "modifiers": [], "raw": raw}

    op_node = test.ops[0]
    op_name = OP_NAMES.get(type(op_node), "other")

    target_node, expected_node, _ = split_target_expected(test.left, test.comparators[0])
    target, modifiers = analyze_target(target_node)
    if target not in ASSERT_TARGETS:
        target = "other"

    expected = literal_repr(expected_node)
    return {
        "target": target,
        "op": op_name,
        "expected": expected,
        "modifiers": modifiers,
        "raw": raw,
    }


def parse_test_function(fn: ast.FunctionDef) -> dict:
    docstring = ast.get_docstring(fn)
    invocations = find_invocations(fn)
    assertions = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            try:
                assertions.append(parse_assertion(node))
            except Exception as e:
                assertions.append({"target": "other", "op": "other", "expected": None,
                                   "modifiers": [], "raw": ast.unparse(node.test),
                                   "_parse_error": str(e)})
    return {
        "docstring": docstring,
        "invocations": invocations,
        "assertions": assertions,
    }


def parse_pytest_file(path: Path) -> dict[str, dict]:
    """Return {test_name: parsed_dict} for every top-level function starting with test_."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as e:
        return {"_file_error": {"error": f"SyntaxError: {e}"}}

    out = {}
    def emit(name: str, fn: ast.FunctionDef):
        try:
            out[name] = parse_test_function(fn)
        except Exception as e:
            out[name] = {"docstring": None, "invocations": [], "assertions": [],
                         "_parse_error": str(e)}

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            emit(node.name, node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name.startswith("test_"):
                    emit(f"{node.name}.{sub.name}", sub)
    return out


def find_tarballs(hf_root: Path, task_id: str) -> dict[str, Path]:
    """Map branch_hash -> tarball path."""
    task_dir = hf_root / task_id / "tests"
    if not task_dir.exists():
        raise FileNotFoundError(f"No HF test cache for {task_id}: {task_dir}")
    return {p.stem.replace(".tar", ""): p.resolve() for p in task_dir.glob("*.tar.gz")}


def process_task(task_id: str, tasks_dir: Path, hf_root: Path, out_fh) -> int:
    """Process one task. Returns number of test records emitted."""
    task_dir = tasks_dir / task_id
    tests_json = json.loads((task_dir / "tests.json").read_text())
    branches = tests_json.get("branches", {})
    tarballs = find_tarballs(hf_root, task_id)

    n_emitted = 0
    for branch_hash, branch_info in branches.items():
        if branch_hash not in tarballs:
            print(f"  WARN: branch {branch_hash} has no tarball", file=sys.stderr)
            continue
        wanted_tests = set(branch_info.get("tests", []))

        with tempfile.TemporaryDirectory() as td:
            try:
                with tarfile.open(tarballs[branch_hash]) as tf:
                    tf.extractall(td)
            except OSError as e:
                # e.g. macOS ENAMETOOLONG on pathologically deep test fixtures (broot).
                print(f"  WARN: branch {branch_hash} extract failed: {e}", file=sys.stderr)
                continue
            test_files = list(Path(td).rglob("eval/tests/test_*.py"))
            file_parses: dict[str, dict[str, dict]] = {}
            for tf_path in test_files:
                file_parses[tf_path.name] = parse_pytest_file(tf_path)

            for full_name in wanted_tests:
                # Names: "[eval.]tests.<file>.<func>[param]" or "[eval.]tests.<file>.<Class>.<func>[param]"
                # Param payload may contain dots, so strip "[...]" before splitting on "."
                bare = full_name.split("[", 1)[0]
                parts = bare.split(".")
                if "tests" not in parts:
                    continue
                idx = parts.index("tests")
                if idx + 2 >= len(parts):
                    continue
                file_stem = parts[idx + 1]
                test_lookup = ".".join(parts[idx + 2 :])  # "func" or "Class.func"
                file_name = f"{file_stem}.py"
                parsed_file = file_parses.get(file_name)
                if not parsed_file:
                    record = {
                        "task_id": task_id, "branch": branch_hash,
                        "test_file": file_name, "test_name": test_lookup,
                        "unparseable": True, "reason": "file_not_found",
                    }
                else:
                    parsed_test = parsed_file.get(test_lookup)
                    if not parsed_test:
                        record = {
                            "task_id": task_id, "branch": branch_hash,
                            "test_file": file_name, "test_name": test_lookup,
                            "unparseable": True, "reason": "test_not_found",
                        }
                    else:
                        record = {
                            "task_id": task_id, "branch": branch_hash,
                            "test_file": file_name, "test_name": test_lookup,
                            "docstring": parsed_test["docstring"],
                            "invocations": parsed_test["invocations"],
                            "assertions": parsed_test["assertions"],
                            "unparseable": False,
                        }
                out_fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                n_emitted += 1
    return n_emitted


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", help="single task_id, e.g. eradman__entr.8e2e8b4")
    p.add_argument("--all", action="store_true", help="process every task in tasks-dir")
    p.add_argument("--tasks-dir", type=Path, required=True)
    p.add_argument("--hf-tests", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    if not args.task and not args.all:
        p.error("--task or --all required")

    if args.task:
        task_ids = [args.task]
    else:
        # Only process tasks that have BOTH source tests.json AND HF tarballs cached.
        cached = {d.name for d in args.hf_tests.iterdir() if d.is_dir() and (d / "tests").exists()}
        task_ids = sorted(
            d.name for d in args.tasks_dir.iterdir()
            if d.is_dir() and (d / "tests.json").exists() and d.name in cached
        )
        print(f"found {len(task_ids)} tasks with both source and HF cache", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as fh:
        total = 0
        for tid in task_ids:
            print(f"parsing {tid}...", file=sys.stderr)
            try:
                n = process_task(tid, args.tasks_dir, args.hf_tests, fh)
                total += n
                print(f"  -> {n} tests", file=sys.stderr)
            except Exception as e:
                print(f"  ERROR {tid}: {e}", file=sys.stderr)

    print(f"\nTotal: {total} test records -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
