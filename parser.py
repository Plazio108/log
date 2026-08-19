import ast
import operator as op
import re
import weakref
from functools import lru_cache
from typing import Any, Dict, Optional, Union, Mapping

# ==========================================
# 1. SAFE AST EVALUATOR & PARSER
# ==========================================

_SAFE_OPERATORS = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.FloorDiv: op.floordiv, ast.Mod: op.mod,
    ast.USub: op.neg, ast.UAdd: op.pos,
}

_SAFE_BUILTINS = {
    "len": len, "str": str, "int": int, "float": float, 
    "bool": bool, "min": min, "max": max, "abs": abs, "round": round
}

def _eval_ast(node: ast.AST, variables: Mapping[str, Any]) -> Any:
    # 1. Primitives & Variables
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        raise ValueError(f"Undefined variable or object: '{node.id}'")
        
    # 2. Object Attributes (e.g. self.w, canvas.color)
    elif isinstance(node, ast.Attribute):
        obj = _eval_ast(node.value, variables)
        if not hasattr(obj, node.attr):
            raise AttributeError(f"Object has no attribute '{node.attr}'")
        return getattr(obj, node.attr)
        
    # 3. Math Operations
    elif isinstance(node, ast.BinOp):
        left = _eval_ast(node.left, variables)
        right = _eval_ast(node.right, variables)
        return _SAFE_OPERATORS[type(node.op)](left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_ast(node.operand, variables)
        return _SAFE_OPERATORS[type(node.op)](operand)

    # 4. Slicing and Indexing (e.g. text[0:5], items[-1])
    elif isinstance(node, ast.Subscript):
        obj = _eval_ast(node.value, variables)
        slice_val = _eval_ast(node.slice, variables)
        return obj[slice_val]
    elif isinstance(node, ast.Slice):
        lower = _eval_ast(node.lower, variables) if node.lower else None
        upper = _eval_ast(node.upper, variables) if node.upper else None
        step = _eval_ast(node.step, variables) if node.step else None
        return slice(lower, upper, step)
    elif isinstance(node, ast.Index): # For compatibility with Python < 3.9
        return _eval_ast(node.value, variables)

    # 5. Function & Method Calls (e.g. len(text), name.upper())
    elif isinstance(node, ast.Call):
        func = _eval_ast(node.func, variables)
        args = [_eval_ast(arg, variables) for arg in node.args]
        
        # Security Guardrail: Only allow safe built-ins or methods of safe primitives (strings/lists/dicts)
        is_safe_builtin = func in _SAFE_BUILTINS.values()
        is_safe_method = hasattr(func, "__self__") and isinstance(func.__self__, (str, int, float, list, tuple, dict))
        
        if is_safe_builtin or is_safe_method:
            return func(*args)
        raise TypeError(f"Execution of callable '{func}' is not allowed for security reasons.")

    # 6. F-Strings formatting (e.g. f"Hello {self.name}")
    elif isinstance(node, ast.JoinedStr):
        return "".join(str(_eval_ast(v, variables)) for v in node.values)
    elif isinstance(node, ast.FormattedValue):
        val = _eval_ast(node.value, variables)
        if node.format_spec:
            fmt = _eval_ast(node.format_spec, variables)
            return format(val, fmt)
        return str(val)

    raise TypeError(f"Unsupported syntax: {type(node).__name__}")


@lru_cache(maxsize=2048)
def _get_parsed_ast(expr_str: str) -> ast.Expression:
    return ast.parse(expr_str, mode="eval")


def parse_expr(
    expr: Any,
    length: Optional[Union[int, float]] = None,
    config: Optional[Dict[str, Any]] = None,
    refs: Optional[Mapping[str, Any]] = None,
) -> Any:
    if expr is None:
        return None
    if not isinstance(expr, str):
        return expr 

    config = config or {}
    
    # Pre-load refs with our safe builtins (len, min, max, etc)
    eval_vars = dict(_SAFE_BUILTINS)
    if refs:
        eval_vars.update(refs)
        
    expr_str = expr.strip()
    if not expr_str:
        return None

    # Handle dynamic length overriding via "|"
    if "|" in expr_str:
        len_expr, target_expr = expr_str.split("|", 1)
        length = parse_expr(len_expr, length=None, config=config, refs=refs)
        expr_str = target_expr.strip()

    base_length = float(length) if length is not None else 0.0

    # Config path replacement (c:key:subkey)
    if "c:" in expr_str:
        def _config_replacer(match: re.Match) -> str:
            keys = match.group(0)[2:].split(":")
            val = config
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    raise KeyError(f"Config path '{match.group(0)}' not found.")
            resolved = parse_expr(val, length=length, config=config, refs=refs)
            return str(resolved)
        expr_str = re.sub(r"c:[\w_]+(?::[\w_]+)*", _config_replacer, expr_str)

    # Percentage parsing: modified regex to ensure it doesn't conflict with string formatting or modulo
    if "%" in expr_str:
        expr_str = re.sub(r"(\d+(?:\.\d+)?)%(?!\w)", lambda m: str((float(m.group(1)) / 100.0) * base_length), expr_str)

    # Inject layout keywords
    eval_vars.update({
        "length": base_length,
        "center": base_length / 2.0,
        "full": base_length,
    })

    try:
        tree = _get_parsed_ast(expr_str)
        return _eval_ast(tree.body, eval_vars)
    except Exception as e:
        raise ValueError(f"Failed to parse expression '{expr_str}': {e}")
