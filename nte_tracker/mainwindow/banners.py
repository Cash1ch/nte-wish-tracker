"""Баннеры: фоновый запрос текущего ивентового баннера, обратный отсчёт, активация."""

import sys
from datetime import datetime

from ..catalog import BANNER_PANEL_KEYS, BANNERS, EVENT_BANNER
from ..config import BANNER_ACTIVATED_PREFIX, BANNER_URLS
from ..errors import blocked
from ..workers.banner_feed import _LIVE_BANNER_THREADS, BannerFetchThread


class BannersMixin:
    """Баннеры: фоновый запрос текущего ивентового баннера, обратный отсчёт, активация."""

    def _refresh_banner_fetch(self):
        """Очередной плановый запрос banners.json (если предыдущий уже закончился)."""
        if self._banner_thread is None:
            self._start_banner_fetch()

    # ---------- НОВОЕ: автоопределение текущего ивентового баннера ----------
    def _start_banner_fetch(self):
        """Запускает фоновый запрос. Ничего не блокирует и не бросает исключений."""
        if not BANNER_URLS or any("YOUR_NAME" in u for u in BANNER_URLS):
            return  # адрес не настроен — остаёмся на стандартном (офлайн) списке
        thread = BannerFetchThread(BANNER_URLS, self)
        thread.fetched.connect(self._on_banner_fetched)
        thread.failed.connect(self._on_banner_failed)
        thread.finished.connect(thread.deleteLater)
        self._banner_thread = thread
        thread.start()

    def _on_banner_user_picked(self, *_):
        """Пользователь сам выбрал пул — автоподстановка больше не должна его менять."""
        self._banner_user_picked = True

    def _on_banner_failed(self, reason: str):
        """Тихий откат: список «Баннер (пул)» остаётся стандартным, окон с ошибкой нет."""
        self._banner_thread = None
        print(f"[баннер] автоопределение недоступно: {reason}", file=sys.stderr)

    def _stamp_banner_activation(self, info: dict):
        """НОВОЕ: запоминает (в settings), когда приложение впервые увидело баннер, и кладёт
        это время в info[...]["activated"]. Ключ зависит от роли (основной / реран) и имени,
        поэтому реран прежнего персонажа получает свежую отметку, а не старую.
        Отметка нужна, когда в JSON нет даты старта: крутки, датированные РАНЬШЕ этого
        момента, к баннеру не относятся и в его счётчик не попадают."""
        now = datetime.now().replace(microsecond=0)
        entries = []
        if info.get("name"):
            entries.append(("current", info))
        rerun = info.get("rerun")
        if rerun and rerun.get("name"):
            entries.append(("rerun", rerun))
        for role, key in (("arc_current", "arc"), ("arc_rerun", "arc_rerun")):
            arc_entry = info.get(key)
            if arc_entry and arc_entry.get("name"):
                entries.append((role, arc_entry))
        for role, entry in entries:
            key = f"{BANNER_ACTIVATED_PREFIX}{role}:{entry['name'].strip().lower()}"
            stamp = None
            saved = self.db.get_setting(key, scoped=True)
            if saved:
                try:
                    stamp = datetime.fromisoformat(saved)
                except ValueError:
                    stamp = None            # испорченное значение — ставим отметку заново
            if stamp is None:
                stamp = now
                self.db.set_setting(key, stamp.isoformat(timespec="seconds"), scoped=True)
            entry["activated"] = stamp

    def _on_banner_fetched(self, info: dict):
        """Успех: подпись пункта «Ивентовый персонаж» получает имя, пункт выбирается.
        ИСПРАВЛЕНО: панель баннеров («Стафф») обновляется ВСЕГДА, даже если основной баннер
        не указан (в JSON только реран) или в форме нет нужного пункта."""
        self._banner_thread = None
        self._stamp_banner_activation(info)   # НОВОЕ: нижняя граница учёта круток баннера
        name = info.get("name") or ""
        idx = self.in_banner.findData(EVENT_BANNER)
        if idx >= 0 and name:
            # Меняем только ТЕКСТ пункта; данные (EVENT_BANNER) остаются прежними,
            # поэтому сохранение круток, счётчики и фильтры работают как раньше.
            # Подпись обновляется в ОБОИХ списках: «Ручная» и «Скриншот».
            for combo in (self.in_banner, self.shot_banner, self.mass_banner):
                combo.setItemText(idx, f"{BANNERS[EVENT_BANNER]} — {name}")
            # Выбираем пункт автоматически, только если пользователь ещё ничего не трогал
            if not self._banner_user_picked and self.in_banner.currentIndex() != idx:
                self.in_banner.setCurrentIndex(idx)  # сам вызовет _sync_form / _update_preview
                # и через сигнал currentIndexChanged переключит список на вкладке «Скриншот»
        # Имя, сроки и реран показываются на панели баннеров вкладки «Стафф»;
        # таймер обратного отсчёта уже идёт — подхватит новые сроки
        self._banner_info = info
        rerun = info.get("rerun")
        print("[баннер] основной: " + (name or "не указан") + "; реран: "
              + (f"{rerun['name']} (до {rerun['end']})" if rerun else "не объявлен"),
              file=sys.stderr)
        for pool_key in BANNER_PANEL_KEYS:
            self.pools[pool_key].set_banners(info)

    def _update_banner_countdown(self, *_):
        """Тик таймера (раз в секунду): обновляет подписи отсчёта на обеих половинах панели
        баннеров («Стафф») по datetime.now(). Не бросает исключений: без данных — «Время не указано»."""
        for pool_key in BANNER_PANEL_KEYS:
            self.pools[pool_key].tick_countdowns()

    def _sync_shot_banner(self, *_):
        """Отражает выбранный пул формы «Ручная» в списке вкладки «Скриншот»."""
        idx = self.in_banner.currentIndex()
        # batch_banner создаётся позже shot_banner — первый вызов идёт ещё без него
        for combo in (self.shot_banner, getattr(self, "batch_banner", None),
                      getattr(self, "mass_banner", None)):
            if combo is not None and idx >= 0 and combo.currentIndex() != idx:
                with blocked(combo):
                    combo.setCurrentIndex(idx)

    def _on_shot_banner_activated(self, idx: int):
        """Пользователь выбрал пул на вкладке «Скриншот» — переносим выбор в форму «Ручная»."""
        if self.in_banner.currentIndex() != idx:
            self.in_banner.setCurrentIndex(idx)
        if self.shot_found:   # тип безымянных строк зависит от баннера — пересобираем список
            self._fill_candidates(keep_state=True)

    def _on_mass_banner_activated(self, idx: int):
        """Выбор пула переносится в форму «Ручная»; тип безымянных строк зависит от баннера,
        поэтому записи пересобираются (флажки и правки времени сохраняются)."""
        if self.in_banner.currentIndex() != idx:
            self.in_banner.setCurrentIndex(idx)
        if self.mass_data and self._mass_thread is None and self._mass_job is None:
            self._mass_start_job(keep_state=True)

    def _stop_banner_thread(self):
        """Аккуратно гасит поток при закрытии окна (запрос ограничен таймаутом)."""
        thread = getattr(self, "_banner_thread", None)
        if thread is None:
            return
        try:
            thread.fetched.disconnect()
            thread.failed.disconnect()
        except TypeError:
            pass
        if thread.isRunning() and not thread.wait(1500):
            # Запрос ещё идёт: отвязываем поток от окна и держим ссылку до завершения,
            # иначе Qt уничтожит работающий QThread и программа упадёт при выходе.
            _LIVE_BANNER_THREADS.add(thread)
            thread.setParent(None)
            thread.finished.connect(lambda t=thread: _LIVE_BANNER_THREADS.discard(t))
        self._banner_thread = None
