"""
GitHub Gist Storage
Хранилище состояния ботов в секретном Gist вместо коммитов в репозиторий
"""
import json
import os
import httpx
from typing import Dict, Any

GIST_TOKEN = os.environ.get("GH_TOKEN", "")
GIST_ID = os.environ.get("GIST_ID", "")

GIST_API = "https://api.github.com/gists"
GIST_HEADERS = {
    "Authorization": f"token {GIST_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}


async def load_all_state() -> Dict[str, Any]:
    """
    Загружает всё состояние из Gist
    Возвращает словарь {имя_файла: содержимое}
    """
    if not GIST_TOKEN or not GIST_ID:
        # Fallback на локальные файлы для локальной разработки
        return _load_from_local_files()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{GIST_API}/{GIST_ID}", headers=GIST_HEADERS)
            response.raise_for_status()
            gist_data = response.json()

        state = {}
        for filename, file_data in gist_data["files"].items():
            try:
                state[filename] = json.loads(file_data["content"])
            except json.JSONDecodeError:
                state[filename] = file_data["content"]

        return state
    except Exception as e:
        print(f"⚠️  Ошибка загрузки из Gist: {e}")
        return _load_from_local_files()


async def save_all_state(state: Dict[str, Any]) -> bool:
    """
    Сохраняет всё состояние в Gist
    Принимает словарь {имя_файла: содержимое}
    """
    if not GIST_TOKEN or not GIST_ID:
        # Fallback на локальные файлы
        _save_to_local_files(state)
        return True

    try:
        files = {}
        for filename, content in state.items():
            files[filename] = {
                "content": json.dumps(content, indent=2, ensure_ascii=False)
            }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(
                f"{GIST_API}/{GIST_ID}",
                headers=GIST_HEADERS,
                json={"files": files, "description": "ErosLab Bot State"}
            )
            response.raise_for_status()
        print("✅ Состояние успешно сохранено в Gist")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения в Gist: {e}")
        _save_to_local_files(state)
        return False


def _load_from_local_files() -> Dict[str, Any]:
    """Загрузка из локальных файлов (fallback)"""
    state = {}
    for file in os.listdir("."):
        if file.endswith(".json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    state[file] = json.load(f)
            except:
                pass
    return state


def _save_to_local_files(state: Dict[str, Any]):
    """Сохранение в локальные файлы (fallback)"""
    for filename, content in state.items():
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, ensure_ascii=False)