# diagnose.py
import sys
from pathlib import Path

print("Current working directory:", Path.cwd())
print("Python path:")
for p in sys.path:
    print(f"  {p}")

# Проверяем структуру
root = Path(__file__).parent if '__file__' in dir() else Path.cwd()
app_dir = root / "app"
print(f"\nApp directory exists: {app_dir.exists()}")
print(f"App directory path: {app_dir}")

if app_dir.exists():
    print(f"Files in app:")
    for f in app_dir.glob("*.py"):
        print(f"  {f.name}")

# Пытаемся импортировать
try:
    import app
    print("\n✅ Модуль app найден")
    print(f"   Path: {app.__file__}")
except ImportError as e:
    print(f"\n❌ Не удалось импортировать app: {e}")