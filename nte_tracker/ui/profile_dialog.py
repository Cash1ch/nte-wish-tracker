"""Окно ввода никнейма, аватарки и сводка профиля."""

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QMessageBox, QVBoxLayout

from ..catalog import (
    ARC_BANNER, arc_kind_by_name, BANNERS, PITY_ARC_EVENT, PITY_ARC_STD, PITY_CHAR_HARD, POOL_TITLES,
)
from ..config import PROFILE_NAME_MAX
from ..database import Database
from ..errors import DatabaseError
from ..labels import _safe_int, fmt_avg
from ..paths import resolve_db_path
from ..stats import _blank_stats
from .widgets import make_button, make_label


# ----------------------------------------------------------------------------
# НОВОЕ: профили — окно ввода никнейма и проверка первого запуска
# ----------------------------------------------------------------------------
class ProfileNameDialog(QDialog):
    """Модальное окно ввода никнейма (первый запуск, новый профиль, переименование)."""

    def __init__(self, db: Database, parent=None, title: str = "Новый профиль",
                 prompt: str = "Введите ваш никнейм", text: str = "",
                 ok_text: str = "Создать", exclude_id=None, closable: bool = True):
        super().__init__(parent)
        self.db, self.exclude_id, self.name = db, exclude_id, ""
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.addWidget(make_label(prompt))
        self.edit = QLineEdit(text)
        self.edit.setMaxLength(PROFILE_NAME_MAX)
        self.edit.setPlaceholderText("Никнейм")
        self.edit.returnPressed.connect(self._accept)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(make_button(ok_text, self._accept, "primary"))
        if closable:
            row.addWidget(make_button("Отмена", self.reject))
        lay.addLayout(row)
        self.edit.selectAll()
        self.edit.setFocus()

    def _accept(self, *_):
        try:
            self.name = self.db.check_profile_name(self.edit.text(), self.exclude_id)
        except DatabaseError as e:
            QMessageBox.warning(self, "Профиль", str(e))
            return
        self.accept()



def ensure_profile(db: Database, parent=None) -> bool:
    """Если в базе нет ни одного профиля (первый запуск или база без профилей) — показывает
    окно «Введите ваш никнейм», создаёт и активирует профиль. При повторных запусках окно
    не показывается. False — пользователь закрыл окно (приложение завершается)."""
    if db.profile_count() > 0:
        if not db.profile_id:
            db.load_active()
        return True
    dlg = ProfileNameDialog(db, parent, "Первый запуск", "Введите ваш никнейм",
                            ok_text="Продолжить", closable=False)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False
    try:
        db.create_profile(dlg.name)
    except DatabaseError as e:
        QMessageBox.critical(parent, "Ошибка", str(e))
        return False
    return True



# ----------------------------------------------------------------------------
# НОВОЕ: окно «Профиль» — аватарка, имя и сводная статистика аккаунта
# ----------------------------------------------------------------------------
PROFILE_AVATAR_KEY = "profile_avatar"      # ключ в settings (на профиль): путь к файлу аватарки



PROFILE_AVATAR_PX = 512                    # сторона сохраняемой квадратной аватарки



PROFILE_AVATAR_FILTER = "Изображения (*.png *.jpg *.jpeg *.webp)"



PROFILE_NEON, PROFILE_PINK, PROFILE_GOLD, PROFILE_MINT = "#00e5ff", "#ff2bd6", "#ffd740", "#7be0a8"



def avatar_dir() -> Path:
    """Папка аватарок рядом с базой данных (создаётся при первом сохранении)."""
    path = resolve_db_path().parent / "avatars"
    path.mkdir(parents=True, exist_ok=True)
    return path



def load_profile_avatar(db: Database) -> QPixmap:
    """Аватарка активного профиля; пустой QPixmap, если её нет или файл пропал."""
    path = db.get_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    if path and Path(path).is_file():
        pm = QPixmap(path)
        if not pm.isNull():
            return pm
    return QPixmap()



def save_profile_avatar(db: Database, source: str) -> QPixmap:
    """Обрезает выбранное изображение до квадрата по центру, плавно масштабирует до
    512×512, сохраняет PNG в папку avatars, а путь — в settings активного профиля."""
    img = QImage(source)
    if img.isNull():
        raise DatabaseError("Не удалось открыть изображение. Поддерживаются PNG, JPG, JPEG и WEBP.")
    side = min(img.width(), img.height())
    img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
    img = img.scaled(PROFILE_AVATAR_PX, PROFILE_AVATAR_PX, Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    try:
        target = avatar_dir() / f"avatar_{db.profile_id}.png"
        saved = img.save(str(target), "PNG")
    except OSError:
        saved = False
    if not saved:
        raise DatabaseError("Не удалось сохранить аватарку.")
    if not db.set_setting(PROFILE_AVATAR_KEY, str(target), scoped=True):
        raise DatabaseError("Не удалось сохранить аватарку в базе данных.")
    return QPixmap.fromImage(img)



def clear_profile_avatar(db: Database) -> None:
    path = db.get_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    db.set_setting(PROFILE_AVATAR_KEY, "", scoped=True)
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass



def profile_summary(stats: dict, history: list) -> list:
    """Статистика отдельно по пулам (ивентовые, стандартные, дуги) по готовым stats и history."""
    out = []
    for key in BANNERS:
        s = stats.get(key) or _blank_stats()
        rows = [e for e in history if e.get("src") == "wish" and e.get("banner") == key
                and e.get("rarity") == 5 and e.get("kind") in ("main", "cashback")]
        best = min((e for e in rows if _safe_int(e.get("p5")) > 0), key=lambda e: _safe_int(e["p5"]),
                   default=None)
        if key == ARC_BANNER:
            ev = sum(1 for e in rows if arc_kind_by_name(e.get("name"), e.get("arc_kind") or "") == "event")
            pity = [("Стандартная S", s["counter_std"], PITY_ARC_STD),
                    ("Ивентовая S", s["counter_ev"], PITY_ARC_EVENT)]
        else:
            ev, pity = 0, [("Гарант S", s["counter"], PITY_CHAR_HARD)]
        out.append({"key": key, "title": POOL_TITLES[key], "total": s["total"], "s": s["r5"],
                    "avg": fmt_avg(s["pities"]), "best": best, "pity": pity,
                    "ev": ev, "st": len(rows) - ev})
    return out
