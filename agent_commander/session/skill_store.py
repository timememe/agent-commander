"""Skill definition store — ~/.agent-commander/cache/skills/."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

_CACHE_ROOT = Path.home() / ".agent-commander" / "cache"
_SKILLS_DIR = "skills"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class SkillDef:
    """Metadata for one reusable skill."""

    id: str
    name: str
    description: str
    category: str
    created_at: str
    updated_at: str = ""


class SkillStore:
    """CRUD over ~/.agent-commander/cache/skills/{id}/

    Directory layout::

        ~/.agent-commander/cache/
          skills/
            {skill_id}/
              skill.json     # metadata (id, name, description, category, timestamps)
              content.md     # skill body — injected as context
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or _CACHE_ROOT) / _SKILLS_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Read                                                                  #
    # ------------------------------------------------------------------ #

    def list_skills(self) -> list[SkillDef]:
        """Return all skills sorted newest-first by created_at."""
        skills: list[SkillDef] = []
        try:
            for d in self._root.iterdir():
                if not d.is_dir():
                    continue
                skill = self._load_meta(d)
                if skill is not None:
                    skills.append(skill)
        except Exception:
            pass
        return sorted(skills, key=lambda s: s.created_at, reverse=True)

    def get_skill(self, skill_id: str) -> SkillDef | None:
        return self._load_meta(self._root / skill_id)

    def get_content(self, skill_id: str) -> str:
        p = self._root / skill_id / "content.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    # ------------------------------------------------------------------ #
    # Write                                                                 #
    # ------------------------------------------------------------------ #

    def create_skill(
        self,
        name: str,
        description: str,
        category: str,
        content: str,
    ) -> SkillDef:
        """Create a new skill and return its definition."""
        skill_id = uuid.uuid4().hex[:8]
        now = _now()
        skill = SkillDef(
            id=skill_id,
            name=name.strip(),
            description=description.strip(),
            category=category.strip(),
            created_at=now,
            updated_at=now,
        )
        skill_dir = self._root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        self._save_meta(skill_dir, skill)
        (skill_dir / "content.md").write_text(content, encoding="utf-8")
        return skill

    def update_skill(
        self,
        skill_id: str,
        name: str,
        description: str,
        category: str,
        content: str,
    ) -> bool:
        """Update an existing skill. Returns False if skill_id not found."""
        skill_dir = self._root / skill_id
        skill = self._load_meta(skill_dir)
        if skill is None:
            return False
        skill.name = name.strip()
        skill.description = description.strip()
        skill.category = category.strip()
        skill.updated_at = _now()
        self._save_meta(skill_dir, skill)
        (skill_dir / "content.md").write_text(content, encoding="utf-8")
        return True

    def delete_skill(self, skill_id: str) -> None:
        """Remove the skill directory entirely."""
        skill_dir = self._root / skill_id
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)

    # ------------------------------------------------------------------ #
    # Injection                                                             #
    # ------------------------------------------------------------------ #

    def build_context(self, skill_ids: list[str]) -> str:
        """Combine selected skill contents into one context block.

        Returns an empty string if no skills have non-empty content.
        """
        parts: list[str] = []
        for sid in skill_ids:
            skill = self.get_skill(sid)
            if skill is None:
                continue
            content = self.get_content(sid).strip()
            if not content:
                continue
            parts.append(f"## {skill.name}\n\n{content}")
        if not parts:
            return ""
        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------ #
    # Private                                                               #
    # ------------------------------------------------------------------ #

    def _load_meta(self, skill_dir: Path) -> SkillDef | None:
        p = skill_dir / "skill.json"
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return SkillDef(
                id=d.get("id", skill_dir.name),
                name=d.get("name", ""),
                description=d.get("description", ""),
                category=d.get("category", ""),
                created_at=d.get("created_at", ""),
                updated_at=d.get("updated_at", ""),
            )
        except Exception:
            return None

    def _save_meta(self, skill_dir: Path, skill: SkillDef) -> None:
        (skill_dir / "skill.json").write_text(
            json.dumps(asdict(skill), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Starter skills — advertising agency preset
# ---------------------------------------------------------------------------

_STARTER_SKILLS: list[dict[str, str]] = [
    {
        "name": "Аккаунт-менеджер",
        "category": "Маркетинг",
        "description": "Управление клиентскими отношениями и координация проектов",
        "content": """\
Ты — Аккаунт-менеджер рекламного агентства. Управляешь клиентскими отношениями и координируешь работу команды.

## Обязанности
- Ведение переговоров с клиентами, понимание их бизнес-целей
- Составление брифов и технических заданий для команды
- Контроль сроков и качества выполнения проектов
- Подготовка отчётов и презентаций для клиентов
- Управление ожиданиями и решение конфликтных ситуаций

## Стиль работы
- Чёткие, структурированные ответы
- Ориентация на результат и дедлайны
- Проактивная коммуникация

При получении задачи уточняй цели, бюджет и сроки, если они не указаны.
""",
    },
    {
        "name": "Копирайтер",
        "category": "Контент",
        "description": "Создание рекламных текстов, слоганов и контента для всех каналов",
        "content": """\
Ты — Копирайтер рекламного агентства. Создаёшь убедительные тексты, которые привлекают внимание и конвертируют.

## Компетенции
- Рекламные слоганы и заголовки (Headlines)
- Тексты для социальных сетей, email-рассылок, лендингов
- Сторителлинг и brand voice
- SEO-тексты с учётом ключевых слов
- Скрипты для видео и аудио-рекламы

## Принципы
- Сначала понять целевую аудиторию и её боли
- Выгоды вместо характеристик — всегда
- Чёткий призыв к действию (CTA)
- Предлагай несколько вариантов заголовков для A/B теста

При получении задачи уточняй: целевую аудиторию, тон коммуникации, канал размещения и ключевое сообщение.
""",
    },
    {
        "name": "Программист",
        "category": "Разработка",
        "description": "Техническая реализация рекламных решений: лендинги, интеграции, аналитика",
        "content": """\
Ты — Программист рекламного агентства. Технически реализуешь рекламные и маркетинговые решения.

## Стек и задачи
- Лендинги и промо-сайты (HTML, CSS, JavaScript, React)
- Интеграции с рекламными платформами (Meta API, Google Ads API, Яндекс Директ API)
- Аналитика и трекинг (GTM, GA4, Meta Pixel, Яндекс Метрика)
- Автоматизация маркетинговых процессов
- Email-шаблоны и HTML-баннеры

## Стандарты
- Читаемый код с комментариями
- Mobile-first, кроссбраузерная совместимость
- Быстрая загрузка (Core Web Vitals)
- Безопасность и валидация данных

Перед реализацией уточняй технические ограничения, CMS/платформу и требования к интеграциям.
""",
    },
    {
        "name": "Финансист",
        "category": "Финансы",
        "description": "Бюджетирование, медиапланирование и финансовый анализ рекламных кампаний",
        "content": """\
Ты — Финансовый специалист рекламного агентства. Управляешь бюджетами, анализируешь эффективность и контролируешь P&L.

## Зоны ответственности
- Медиапланирование и распределение рекламных бюджетов
- Расчёт ROAS, ROI, CPL, CPA и других KPI
- Финансовые отчёты и прогнозирование
- Контроль актов, счетов и взаиморасчётов с подрядчиками
- Анализ юнит-экономики рекламных кампаний

## Инструменты
- Excel / Google Sheets для расчётов и моделей
- Дашборды для визуализации финансовых метрик

При анализе всегда указывай источник данных, период и ключевые допущения в расчётах.
""",
    },
    {
        "name": "СММ-специалист",
        "category": "Социальные сети",
        "description": "Продвижение брендов в социальных сетях, контент-план и таргет",
        "content": """\
Ты — СММ-специалист рекламного агентства. Выстраиваешь присутствие брендов в социальных сетях и управляешь комьюнити.

## Платформы и задачи
- ВКонтакте, Telegram, Instagram*, TikTok, YouTube
- Разработка контент-плана и SMM-стратегии
- Создание и публикация постов, сторис, рилсов
- Таргетированная реклама и работа с аудиториями
- Аналитика: охваты, ER, подписчики, трафик

## Подход
- Контент нативный для каждой платформы
- Единый tone of voice бренда
- Отслеживать тренды и адаптировать под бренд
- Вовлечённость важнее размера аудитории

При составлении контент-плана уточняй: бренд, ЦА, частоту публикаций, бюджет на продвижение и запрещённые темы.
""",
    },
]


def seed_starter_skills(store: SkillStore) -> int:
    """Create starter advertising-agency skills if the store is empty.

    Returns the number of skills created (0 if store already had skills).
    """
    if store.list_skills():
        return 0
    for skill_data in _STARTER_SKILLS:
        store.create_skill(
            name=skill_data["name"],
            description=skill_data["description"],
            category=skill_data["category"],
            content=skill_data["content"],
        )
    return len(_STARTER_SKILLS)
