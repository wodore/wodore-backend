#!/usr/bin/env python
"""
Generate API documentation for the Wodore backend.

This script creates a navigable API reference from the Python modules in the server directory.
"""

import os
import sys
from pathlib import Path

# Import mkdocs_gen_files early to ensure it's available
import mkdocs_gen_files

# Set up paths
root = Path(__file__).parent.parent
server_dir = root / "server"
docs_dir = root / "docs"
reference_dir = docs_dir / "reference"

# Add project root to Python path
sys.path.insert(0, str(root))
sys.path.insert(0, str(server_dir))

# Set environment variables
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.local")
os.environ["PYTHONPATH"] = ":".join([str(root), str(server_dir)])

# Create reference directory if it doesn't exist
reference_dir.mkdir(parents=True, exist_ok=True)

# Initialize variables
DJANGO_AVAILABLE = False
INSTALLED_APPS = []

# Try to import Django
try:
    import django
    from django.apps import apps as django_apps

    django.setup()
    DJANGO_AVAILABLE = True
    INSTALLED_APPS = [app.name for app in django_apps.get_app_configs()]
    print(f"Found installed apps: {INSTALLED_APPS}")
except ImportError:
    print("Warning: Django not available. Only generating basic documentation.")
    DJANGO_AVAILABLE = False
    INSTALLED_APPS = []
except Exception as e:
    print(f"Warning: Failed to initialize Django: {e}")
    DJANGO_AVAILABLE = False
    INSTALLED_APPS = []

# Initialize navigation
nav = mkdocs_gen_files.Nav()

# Define source directory
src = server_dir


def should_skip(path):
    """Determine if a file should be skipped in documentation."""
    # Convert path to string for easier checking
    path_str = str(path)

    # Skip test directories and files
    if "tests/" in path_str or "/tests/" in path_str:
        return "Test file"

    # Skip migrations
    if "migrations/" in path_str:
        return "Migration file"

    # Skip private modules (except __init__.py)
    if any(
        part.startswith("_") and part != "__init__" and not part.endswith(".py")
        for part in path.parts
    ):
        return "Private module"

    # Skip files that start with underscore (except __init__.py)
    if path.stem.startswith("_") and path.stem != "__init__":
        return "Private module"

    # Skip specific files
    skip_files = {
        "asgi.py",
        "urls.py",
        "wsgi.py",
        "manage.py",
        "celery.py",
        "admin.py",
        "apps.py",
        "signals.py",
    }
    if path.name in skip_files:
        return "Excluded file"

    # Check if the file is in an installed app
    try:
        rel_path = path.relative_to(server_dir)
        app_path = str(rel_path).split(os.sep)[0]

        # Skip if not in an installed app
        if (
            DJANGO_AVAILABLE
            and app_path not in INSTALLED_APPS
            and app_path not in ("core", "settings")
        ):
            return f"Not in installed apps: {app_path}"
    except ValueError:
        # If we can't get relative path, skip
        return "Could not determine relative path"

    return None


def get_module_path(path):
    """Convert file path to Python module path."""
    try:
        # Get relative path from project root
        rel_path = path.relative_to(root).with_suffix("")
        # Convert to module path
        return str(rel_path).replace(os.sep, ".")
    except Exception as e:
        print(f"Warning: Could not get module path for {path}: {e}")
        return ""


# Generate documentation for Python files
for path in sorted(server_dir.rglob("*.py")):
    # Skip files that should not be documented
    skip_reason = should_skip(path)
    if skip_reason:
        print(f"Skipping {path}: {skip_reason}")
        continue

    # Get module path
    module_path = get_module_path(path)
    if not module_path:
        print(f"Warning: Could not determine module path for {path}")
        continue

    # Convert module path to documentation path
    doc_path = path.relative_to(server_dir).with_suffix(".md")
    full_doc_path = Path("reference", doc_path)

    # Handle __init__.py files
    if path.name == "__init__.py":
        if len(module_path.split(".")) > 1:
            doc_path = doc_path.parent / "index.md"
            full_doc_path = full_doc_path.parent / "index.md"

    # Add to navigation
    nav_parts = tuple(module_path.split(".")[1:])  # Remove 'server' prefix
    if nav_parts:  # Only add if we have valid navigation parts
        nav[nav_parts] = str(doc_path)

        # Create the markdown file
        with mkdocs_gen_files.open(full_doc_path, "w") as f:
            f.write(f"# `{'.'.join(nav_parts)}`\n\n")
            f.write(f"::: {'.'.join(nav_parts)}\n")

    try:
        # Calculate module path and documentation path
        module_path = get_module_path(path)
        doc_path = path.relative_to(src).with_suffix(".md")
        full_doc_path = Path("reference", doc_path)

        # Get navigation parts (remove 'server' prefix)
        parts = tuple(module_path.split(".")[1:])

        # Skip if no valid parts
        if not parts:
            print(f"Skipping empty module path: {path}")
            continue

        # Handle __init__.py files
        if path.name == "__init__.py":
            if len(parts) > 1:
                parts = parts[:-1]  # Remove __init__ from path
                doc_path = doc_path.parent / "index.md"
                full_doc_path = full_doc_path.parent / "index.md"
            else:
                parts = ("server",)  # Root __init__.py

        # Skip if still no valid parts
        if not parts:
            print(f"Skipping empty module path after processing: {path}")
            continue

        print(f"Documenting: {path} as {'.'.join(parts)}")

        # Add to navigation
        nav[parts] = str(doc_path)

        # Create the markdown file
        with mkdocs_gen_files.open(full_doc_path, "w") as fd:
            # Write the module reference
            ident = ".".join(parts)
            fd.write(f"# `{ident}`\n\n")
            fd.write(f"::: {ident}")

        # Set edit path for the generated file
        mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(root))
    except Exception as e:
        print(f"Error processing {path}: {str(e)}")
        continue

# Create a summary file with the navigation structure
with mkdocs_gen_files.open("reference/SUMMARY.md", "w") as nav_file:
    nav_file.write("# API Reference\n\n")
    nav_file.writelines(nav.build_literate_nav())

print("\nDocumentation generation complete!")
print("Run 'mkdocs serve' to preview the documentation.")
print("Note: You may need to install mkdocs-material for the best viewing experience.")
