#!/usr/bin/env python3
"""
Simple HTML template validation script.
Checks the basic syntax of template files.
"""

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
import os

def validate_templates():
    """Validate all HTML templates."""
    template_dir = 'templates'
    env = Environment(loader=FileSystemLoader(template_dir))

    templates = ['base.html', 'index.html', 'detail.html']

    print("=" * 50)
    print("HTML Template Validation")
    print("=" * 50)

    all_valid = True

    for template_name in templates:
        try:
            template = env.get_template(template_name)
            print(f"✅ {template_name} - syntax OK")
        except TemplateSyntaxError as e:
            print(f"❌ {template_name} - syntax error:")
            print(f"   Line {e.lineno}: {e.message}")
            all_valid = False
        except Exception as e:
            print(f"❌ {template_name} - error: {str(e)}")
            all_valid = False

    print("=" * 50)
    if all_valid:
        print("✅ All templates passed validation!")
        return 0
    else:
        print("❌ Syntax errors found; please check the files above")
        return 1

if __name__ == '__main__':
    exit(validate_templates())
