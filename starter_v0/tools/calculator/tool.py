from __future__ import annotations

import ast
import math
import operator
from typing import Any

from tools._shared import err


OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

# Guards: the model controls `expression`, so it must not be able to hang the agent
# (e.g. "9**9**9") or return a number too large to serialize into the tool-results JSON.
MAX_EXPRESSION_CHARS = 200
MAX_EXPONENT = 1000
MAX_ABS_RESULT = 1e100


def _check_size(value: int | float) -> int | float:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Result is not a finite number")
    if abs(value) > MAX_ABS_RESULT:
        raise ValueError("Result is too large")
    return value


def _evaluate(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return _check_size(node.value)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value

    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"Exponent larger than {MAX_EXPONENT} is not allowed")
        if isinstance(node.op, ast.Pow) and abs(left) > 1 and abs(right) * math.log10(abs(left)) > 100:
            raise ValueError("Result is too large")
        return _check_size(OPERATORS[type(node.op)](left, right))

    raise ValueError("Expression contains an unsupported operation")


def calculator(expression: str = "") -> dict[str, Any]:
    try:
        if isinstance(expression, bool) or not isinstance(expression, (str, int, float)):
            raise ValueError("Expression must be a string such as '27 * 14'")
        expression = str(expression)
        if not expression.strip():
            raise ValueError("Expression must not be empty")
        if len(expression) > MAX_EXPRESSION_CHARS:
            raise ValueError(f"Expression longer than {MAX_EXPRESSION_CHARS} characters")

        tree = ast.parse(expression, mode="eval")
        result = _evaluate(tree.body)

        return {
            "tool": "calculator",
            "expression": expression,
            "result": result,
        }
    except Exception as exc:
        return err("calculator", exc)
