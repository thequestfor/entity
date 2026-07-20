import ast
import operator
import re


OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos
}


class ArithmeticHandler:
    def answer(self, text):
        expression = self._extract_expression(text)

        if not expression:
            return None

        try:
            result = self._eval(ast.parse(expression, mode="eval").body)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
            return None

        return f"{expression} = {self._format_result(result)}."

    def _extract_expression(self, text):
        normalized = text.lower()
        normalized = normalized.replace("times", "*")
        normalized = normalized.replace("multiplied by", "*")
        normalized = normalized.replace("plus", "+")
        normalized = normalized.replace("minus", "-")
        normalized = normalized.replace("divided by", "/")

        candidates = re.findall(
            r"(?<!\w)[\d\s+\-*/().%]+(?!\w)",
            normalized
        )

        for candidate in candidates:
            candidate = candidate.strip()

            if not re.search(r"\d", candidate):
                continue

            if not re.search(r"[+\-*/%]", candidate):
                continue

            return re.sub(r"\s+", " ", candidate)

        return None

    def _eval(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value

        if isinstance(node, ast.BinOp):
            operator_type = type(node.op)

            if operator_type not in OPERATORS:
                raise ValueError("Unsupported operator.")

            left = self._eval(node.left)
            right = self._eval(node.right)
            return OPERATORS[operator_type](left, right)

        if isinstance(node, ast.UnaryOp):
            operator_type = type(node.op)

            if operator_type not in OPERATORS:
                raise ValueError("Unsupported operator.")

            return OPERATORS[operator_type](self._eval(node.operand))

        raise ValueError("Unsupported expression.")

    def _format_result(self, result):
        if isinstance(result, float) and result.is_integer():
            return str(int(result))

        return str(result)
