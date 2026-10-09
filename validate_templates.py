#!/usr/bin/env python3
"""
简单的HTML模板验证脚本
检查模板文件的基本语法
"""

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError
import os

def validate_templates():
    """验证所有HTML模板"""
    template_dir = 'templates'
    env = Environment(loader=FileSystemLoader(template_dir))

    templates = ['base.html', 'index.html', 'detail.html']

    print("=" * 50)
    print("HTML 模板验证")
    print("=" * 50)

    all_valid = True

    for template_name in templates:
        try:
            template = env.get_template(template_name)
            print(f"✅ {template_name} - 语法正确")
        except TemplateSyntaxError as e:
            print(f"❌ {template_name} - 语法错误:")
            print(f"   行 {e.lineno}: {e.message}")
            all_valid = False
        except Exception as e:
            print(f"❌ {template_name} - 错误: {str(e)}")
            all_valid = False

    print("=" * 50)
    if all_valid:
        print("✅ 所有模板验证通过！")
        return 0
    else:
        print("❌ 存在语法错误，请检查上述文件")
        return 1

if __name__ == '__main__':
    exit(validate_templates())
