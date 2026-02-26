"""Platform capabilities context — injected into every new agent session.

Tells the agent which Python packages are already bundled so it never
runs unnecessary ``pip install`` commands.
"""

from __future__ import annotations

PLATFORM_CONTEXT = """\
## Встроенные возможности платформы Agent Commander

### Предустановленные Python-пакеты
Все пакеты ниже уже установлены — используй их напрямую, pip install не нужен:

**Работа с документами:**
- `openpyxl` — Excel (.xlsx): `import openpyxl` / `openpyxl.load_workbook(path)`
- `python-docx` — Word (.docx): `from docx import Document`
- `python-pptx` — PowerPoint (.pptx): `from pptx import Presentation`
- `lxml` — XML/HTML: `from lxml import etree`
- `Pillow` — изображения: `from PIL import Image`

**Утилиты:**
- `pydantic` — модели и валидация: `from pydantic import BaseModel`
- `rich` — форматированный вывод: `from rich.console import Console`
- `loguru` — логирование: `from loguru import logger`

**Стандартная библиотека Python** (всегда доступна):
`csv`, `json`, `sqlite3`, `pathlib`, `re`, `datetime`, `subprocess`, `os`, `shutil`, `glob`, `zipfile`, `io`, `base64`

### Доступные инструменты агента
`read_file` · `write_file` · `edit_file` · `run_command` · `glob` · `grep` · `list_dir` · `web_fetch`

При работе с Excel/Word/PowerPoint всегда используй перечисленные пакеты — они встроены в приложение.\
"""
