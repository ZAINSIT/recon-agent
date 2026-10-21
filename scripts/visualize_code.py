"""
visualize_code.py — Generate a call graph of the repository.

Parses all .py files in src/ and shows which functions call which other functions.
Only shows internal functions (ignores built-ins and library calls).
Outputs eval/code_graph.html.
"""

import ast
from pathlib import Path
import plotly.graph_objects as go

SRC_DIR = Path("src")
OUT_HTML = Path("eval/code_graph.html")

def get_defined_functions(file_paths):
    """First pass: find every function name defined in the repo."""
    defined = set()
    for file_path in file_paths:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                defined.add(node.name)
    return defined

def extract_calls(file_path, defined_funcs):
    """Second pass: find calls that match our internal functions."""
    with open(file_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    edges = []
    current_func = None

    class CallVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            nonlocal current_func
            previous = current_func
            current_func = node.name
            self.generic_visit(node)
            current_func = previous

        def visit_Call(self, node):
            if current_func:
                # Get the name being called
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                
                # Only add if it's one of OUR functions
                if name and name in defined_funcs:
                    edges.append((current_func, name))
            self.generic_visit(node)

    CallVisitor().visit(tree)
    return edges

def main():
    py_files = list(SRC_DIR.glob("*.py"))
    eval_file = Path("eval/harness.py")
    if eval_file.exists():
        py_files.append(eval_file)

    # 1. Find all functions we defined
    our_functions = get_defined_functions(py_files)
    
    # 2. Find the edges between them
    edges = []
    for py_file in py_files:
        edges.extend(extract_calls(py_file, our_functions))

    # Deduplicate and remove self-loops
    edges = list(set([(u, v) for u, v in edges if u != v]))

    if not edges:
        print("No internal function calls found.")
        return

    # 3. Prepare Plotly network graph
    sources = [u for u, v in edges]
    targets = [v for u, v in edges]
    
    nodes = list(set(sources + targets))
    node_indices = {node: i for i, node in enumerate(nodes)}
    
    source_idx = [node_indices[u] for u in sources]
    target_idx = [node_indices[v] for v in targets]

    # Color nodes based on what file they likely belong to (rough heuristic)
    # Pipeline & Main in blue, Stages in green, Validator in orange
    colors = []
    for n in nodes:
        if n in ["main", "run", "pipeline"]:
            colors.append("#6366f1") # Blue
        elif n in ["validate", "ValidatorResult"]:
            colors.append("#f59e0b") # Orange
        elif n.startswith("stage"):
            colors.append("#10b981") # Green
        else:
            colors.append("#94a3b8") # Grey

    fig = go.Figure(data=[go.Sankey(
        node=dict(
            label=nodes,
            pad=20,
            thickness=20,
            line=dict(color="black", width=0.5),
            color=colors
        ),
        link=dict(
            source=source_idx,
            target=target_idx,
            value=[1] * len(edges),
            color="rgba(148,163,184,0.4)"
        )
    )])

    fig.update_layout(
        title_text="Code Flow: Internal Function Calls",
        font=dict(size=14, family="Arial"),
        height=800
    )

    OUT_HTML.parent.mkdir(exist_ok=True)
    fig.write_html(OUT_HTML)
    print(f"Wrote {OUT_HTML}")
    print(f"Found {len(nodes)} functions and {len(edges)} internal connections.")

if __name__ == "__main__":
    main()