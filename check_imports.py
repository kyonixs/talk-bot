import sys
import traceback

modules = [
    'services.stock_service',
    'services.technical_service',
    'config.gemini_config',
    'services.gemini_service',
    'prompts.stock_prompts',
    'cogs.stock_report'
]

has_error = False
for mod in modules:
    try:
        __import__(mod)
        print(f"OK: {mod}")
    except Exception as e:
        print(f"ERROR in {mod}:\n")
        traceback.print_exc()
        has_error = True

if has_error:
    sys.exit(1)
