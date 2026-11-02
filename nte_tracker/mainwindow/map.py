"""Вкладка «Карта» главного окна (миксин) и мост перевода."""

import json
import tempfile
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QObject, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..constellation.geometry import _map_translate_en_ru
from ..paths import app_dir
from ..ui.widgets import make_label


class _MapTrBridge(QObject):
    done = pyqtSignal(dict, list)




class MapMixin:
    """Вкладка «Карта»: встроенный браузер, метки и перевод интерфейса сайта."""

    # ---------- НОВОЕ: вкладка «Симуляция» ----------
    # ---------- Интерактивная карта (встроенный браузер, грузится при первом открытии) ----------
    MAP_URL = "https://nte.stardb.gg/map"

    MAP_CACHE_MAX_MB = 300     # ОПТИМИЗАЦИЯ: размер дискового кэша карты (картинки не качаются заново)

    MAP_RU_DICT = {
        "Tasks": "Задачи",
        "Quests": "Квесты",
        "Achievements": "Достижения",
        "Tracker": "Трекер",
        "Tools": "Инструменты",
        "Map": "Карта",
        "Log In": "Войти",
        "Login": "Войти",
        "Sign In": "Войти",
        "Log Out": "Выйти",
        "Viewing as guest": "Просмотр в режиме гостя",
        "Marker progress is saved locally. Sign in to sync it across devices, post comments, and vote.":
            "Прогресс по меткам сохраняется локально. Войдите, чтобы синхронизировать его между устройствами, писать комментарии и голосовать.",
        "Neverness to Everness Interactive Map": "Интерактивная карта Neverness to Everness",
        "Hide Collected": "Скрыть собранное",
        "Show Collected": "Показать собранное",
        "Reset": "Сбросить",
        "Map": "Карта",
        "District": "Район",
        "All districts": "Все районы",
        "Hethereau": "Хетерё",
        "Filters": "Фильтры",
        "Progress": "Прогресс",
        "Info": "Инфо",
        "Collectable": "Коллекционные",
        "Collectible": "Коллекционные",
        "Collectables": "Коллекционные",
        "Collectibles": "Коллекционные",
        "All": "Все",
        "None": "Ничего",
        "Wanderer's Journal": "Журнал странника",
        "Wanderer\u2019s Journal": "Журнал странника",
        "RereRero Phone": "Телефон РереРеро",
        "Wertheimer Tower": "Башня Вертхаймера",
        "Oracle Stone": "Камень оракула",
        "Gift from \"21\"": "Подарок от «21»",
        "Gift from \u201c21\u201d": "Подарок от «21»",
        "Strange Tales": "Странные истории",
        "Check-in": "Отметка",
        "Side Quest": "Побочный квест",
        "Anomaly Commission": "Заказ на аномалию",
        "Anomaly Commissions": "Заказы на аномалии",
        "Anomaly Hunt": "Охота на аномалии",
        "Move cursor over map": "Наведите курсор на карту",
        "Middle-click to copy": "Средняя кнопка мыши — копировать",
        "Search": "Поиск",
        "Settings": "Настройки",
        "Close": "Закрыть",
        "Collected": "Собрано",
        "Comments": "Комментарии",
        "Loading": "Загрузка",
        "Loading...": "Загрузка...",
        "Loading\u2026": "Загрузка…",
        "Zoom In": "Приблизить",
        "Zoom Out": "Отдалить",
        "Legend": "Легенда",
        "Layers": "Слои",
        "Categories": "Категории",
        "Category": "Категория",
        "Description": "Описание",
        "Location": "Местоположение",
        "Coordinates": "Координаты",
        "Mark as collected": "Отметить как собранное",
        "Mark as uncollected": "Снять отметку",
        "Collect": "Собрать",
        "Home": "Главная",
        "Characters": "Персонажи",
        "Weapons": "Оружие",
        "Items": "Предметы",
        "Guides": "Гайды",
        "News": "Новости",
    }

    MAP_MARKS_JS = r"""
(function () {
  if (window.__nteMarksInit) { return; }
  window.__nteMarksInit = true;
  var LS_KEY = "nte_user_markers_v1";
  var COLORS = ["#ff9100", "#ff5252", "#69f0ae", "#40c4ff", "#e040fb", "#ffd740"];
  var SHAPES = ["", "?", "!", "\u2191", "\u2193", "\u2605", "\u2665", "\u2714", "\u2716",
                "\u2691", "\u2620", "\u25C6", "\u2302"];
  var layer = null, world = null, vp = null, mapKey = "", lastSig = "", popup = null, data = {};

  function load() {
    try { data = JSON.parse(localStorage.getItem(LS_KEY) || "{}") || {}; } catch (e) { data = {}; }
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(data)); } catch (e) {}
  }
  load();

  var st = document.createElement("style");
  st.setAttribute("data-nte-skip", "1");
  st.textContent =
    ".nte-user-layer{position:fixed;left:0;top:0;width:0;height:0;overflow:hidden;pointer-events:none;z-index:900}" +
    ".nte-pin{position:absolute;left:0;top:0;width:0;height:0;pointer-events:none}" +
    ".nte-pin-body{position:absolute;left:-12px;top:-30px;width:24px;height:30px;" +
    "pointer-events:auto;cursor:pointer}" +
    ".nte-pin-dot{position:absolute;left:0;top:0;width:24px;height:24px;border-radius:50%;" +
    "border:2px solid #fff;box-sizing:border-box;box-shadow:0 0 6px rgba(0,0,0,.7);background:var(--c);" +
    "display:flex;align-items:center;justify-content:center;color:#fff;" +
    "font:700 14px/1 'Segoe UI Symbol','Segoe UI',sans-serif;text-shadow:0 0 2px rgba(0,0,0,.7)}" +
    ".nte-pin-tail{position:absolute;left:7px;top:22px;width:0;height:0;border-left:5px solid transparent;" +
    "border-right:5px solid transparent;border-top:8px solid var(--c)}" +
    ".nte-pin-label{position:absolute;left:30px;top:2px;white-space:nowrap;font:600 12px/1.2 sans-serif;" +
    "color:#fff;background:rgba(10,12,24,.85);padding:2px 6px;border-radius:6px;border:1px solid var(--c);" +
    "pointer-events:none}" +
    ".nte-popup{position:fixed;z-index:2147483000;width:236px;box-sizing:border-box;padding:12px;" +
    "background:#141a2e;border:1px solid #ff9100;border-radius:10px;color:#fff;" +
    "font:13px/1.3 sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.6)}" +
    ".nte-pop-title{font-weight:700;color:#ffb74d;margin-bottom:8px}" +
    ".nte-pop-input{width:100%;box-sizing:border-box;padding:6px 8px;border-radius:6px;" +
    "border:1px solid #455;background:#0b1020;color:#fff;font:13px sans-serif;outline:none}" +
    ".nte-pop-input:focus{border-color:#ff9100}" +
    ".nte-pop-shapes{display:flex;flex-wrap:wrap;gap:4px;margin-top:10px}" +
    ".nte-sh{width:28px;height:28px;box-sizing:border-box;border-radius:6px;border:1px solid #455;" +
    "background:#0b1020;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;" +
    "font:700 15px/1 'Segoe UI Symbol','Segoe UI',sans-serif}" +
    ".nte-sh.on{border-color:#ff9100;background:#2a2f4a}" +
    ".nte-pop-colors{display:flex;gap:6px;margin:10px 0}" +
    ".nte-sw{width:22px;height:22px;border-radius:50%;cursor:pointer;border:2px solid transparent;box-sizing:border-box}" +
    ".nte-sw.on{border-color:#fff}" +
    ".nte-pop-btns{display:flex;gap:6px;justify-content:flex-end}" +
    ".nte-pop-btns button{padding:5px 10px;border-radius:6px;border:1px solid #ff9100;background:#1d2540;" +
    "color:#fff;cursor:pointer;font:600 12px sans-serif}" +
    ".nte-pop-btns button.ok{background:#ff9100;color:#111}" +
    ".nte-pop-btns button.del{border-color:#ff5252;color:#ff8a80}";
  (document.head || document.documentElement).appendChild(st);

  function closePopup() {
    if (popup && popup.parentNode) { popup.parentNode.removeChild(popup); }
    popup = null;
  }

  function openPopup(cx, cy, m, isNew) {
    closePopup();
    var color = m.color || COLORS[0];
    var shape = m.shape || "";
    var p = document.createElement("div");
    p.className = "nte-popup";
    p.setAttribute("data-nte-skip", "1");
    p.innerHTML = '<div class="nte-pop-title"></div>' +
      '<input class="nte-pop-input" type="text" maxlength="60" placeholder="Название метки">' +
      '<div class="nte-pop-shapes"></div><div class="nte-pop-colors"></div><div class="nte-pop-btns"></div>';
    p.querySelector(".nte-pop-title").textContent = isNew ? "Новая метка" : "Моя метка";
    var input = p.querySelector(".nte-pop-input");
    input.value = m.name || "";
    var shs = p.querySelector(".nte-pop-shapes");
    SHAPES.forEach(function (g) {
      var sh = document.createElement("span");
      sh.className = "nte-sh" + (g === shape ? " on" : "");
      sh.textContent = g === "" ? "\u25CF" : g;
      sh.addEventListener("click", function () {
        shape = g;
        Array.prototype.forEach.call(shs.children, function (x) { x.className = "nte-sh"; });
        sh.className = "nte-sh on";
      });
      shs.appendChild(sh);
    });
    var sws = p.querySelector(".nte-pop-colors");
    COLORS.forEach(function (c) {
      var sw = document.createElement("span");
      sw.className = "nte-sw" + (c === color ? " on" : "");
      sw.style.background = c;
      sw.addEventListener("click", function () {
        color = c;
        Array.prototype.forEach.call(sws.children, function (x) { x.className = "nte-sw"; });
        sw.className = "nte-sw on";
      });
      sws.appendChild(sw);
    });
    var btns = p.querySelector(".nte-pop-btns");
    function mk(text, cls, fn) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = cls;
      b.textContent = text;
      b.addEventListener("click", fn);
      btns.appendChild(b);
    }
    function apply() {
      m.name = input.value.trim();
      m.color = color;
      m.shape = shape;
      if (isNew) {
        m.id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        (data[mapKey] = data[mapKey] || []).push(m);
      }
      save();
      closePopup();
      render();
    }
    if (!isNew) {
      mk("Удалить", "del", function () {
        data[mapKey] = (data[mapKey] || []).filter(function (x) { return x.id !== m.id; });
        save();
        closePopup();
        render();
      });
    }
    mk("Отмена", "", closePopup);
    mk(isNew ? "Добавить" : "Сохранить", "ok", apply);
    ["keydown", "keyup", "keypress", "mousedown", "mouseup", "click", "wheel", "contextmenu"].forEach(function (ev) {
      p.addEventListener(ev, function (e) { e.stopPropagation(); });
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { apply(); }
      else if (e.key === "Escape") { closePopup(); }
    });
    document.body.appendChild(p);
    p.style.left = Math.max(4, Math.min(cx, window.innerWidth - 244)) + "px";
    p.style.top = Math.max(4, Math.min(cy, window.innerHeight - 240)) + "px";
    popup = p;
    input.focus();
  }

  function makePin(m) {
    var pin = document.createElement("div");
    pin.className = "nte-pin";
    pin.__m = m;
    pin.style.setProperty("--c", m.color || COLORS[0]);
    pin.innerHTML = '<div class="nte-pin-body"><div class="nte-pin-dot"></div><div class="nte-pin-tail"></div>' +
      (m.name ? '<div class="nte-pin-label"></div>' : "") + "</div>";
    var lab = pin.querySelector(".nte-pin-label");
    if (lab) { lab.textContent = m.name; }
    pin.querySelector(".nte-pin-dot").textContent = m.shape || "";
    var body = pin.querySelector(".nte-pin-body");
    body.__m = m;
    body.addEventListener("click", function (e) {
      e.stopPropagation();
      openPopup(e.clientX, e.clientY, m, false);
    });
    return pin;
  }

  function render() {
    if (!layer) { return; }
    while (layer.firstChild) { layer.removeChild(layer.firstChild); }
    (data[mapKey] || []).forEach(function (m) { layer.appendChild(makePin(m)); });
    lastSig = "";
  }

  function ensure() {
    var w = document.querySelector(".map-world");
    var v = document.querySelector(".map-viewport");
    if (!w || !v || !w.offsetWidth) {
      if (layer) { layer.style.display = "none"; }
      return;
    }
    world = w;
    vp = v;
    if (!layer || layer.parentNode !== document.body) {
      layer = document.createElement("div");
      layer.className = "nte-user-layer";
      layer.setAttribute("data-nte-skip", "1");
      document.body.appendChild(layer);
      mapKey = "";
    }
    layer.style.display = "";
    var key = w.offsetWidth + "x" + w.offsetHeight;
    if (key !== mapKey) {
      mapKey = key;
      render();
    }
  }

  function tick() {
    if (layer && world && vp && world.isConnected && vp.isConnected && world.offsetWidth) {
      var wr = world.getBoundingClientRect();
      var vr = vp.getBoundingClientRect();
      var s = wr.width / world.offsetWidth;
      var sig = [wr.left, wr.top, s, vr.left, vr.top, vr.width, vr.height].join(",");
      if (sig !== lastSig) {
        lastSig = sig;
        layer.style.left = vr.left + "px";
        layer.style.top = vr.top + "px";
        layer.style.width = vr.width + "px";
        layer.style.height = vr.height + "px";
        var pins = layer.children;
        for (var i = 0; i < pins.length; i++) {
          var m = pins[i].__m;
          pins[i].style.transform = "translate3d(" + (wr.left + m.x * s - vr.left) + "px," +
                                    (wr.top + m.y * s - vr.top) + "px,0)";
        }
      }
    }
    requestAnimationFrame(tick);
  }

  document.addEventListener("mousedown", function (e) {
    if (popup && !popup.contains(e.target)) { closePopup(); }
  }, true);

  // НОВОЕ: элементы самого сайта (метки-аномалии, кнопки, всплывающие окна, панели) —
  // правый клик по ним НЕ открывает окно «Новая метка»; оно только на пустом месте карты.
  function isSiteUi(t, v) {
    var vr = v.getBoundingClientRect();
    for (var el = t; el && el !== v && el !== document.body; el = el.parentElement) {
      var nm = el.nodeName;
      if (nm === "A" || nm === "BUTTON" || nm === "INPUT" || nm === "TEXTAREA" ||
          nm === "SELECT" || nm === "LABEL") { return true; }
      var role = el.getAttribute ? el.getAttribute("role") : "";
      var cls = (typeof el.className === "string") ? el.className
              : ((el.getAttribute && el.getAttribute("class")) || "");
      if (role === "button" || role === "dialog" || role === "menu" ||
          /marker|popup|popover|tooltip|modal|panel|sidebar/i.test(cls)) {
        var r = el.getBoundingClientRect();
        // большие обёртки (на пол-экрана и больше) не считаются элементами интерфейса
        if (r.width < vr.width * 0.5 && r.height < vr.height * 0.5) { return true; }
      }
    }
    return false;
  }

  document.addEventListener("contextmenu", function (e) {
    var v = document.querySelector(".map-viewport");
    if (!v || !v.contains(e.target)) { return; }
    if (e.target.closest && e.target.closest(".nte-popup")) { return; }
    if (isSiteUi(e.target, v)) { return; }
    e.preventDefault();
    ensure();
    if (!layer || !world) { return; }
    var body = e.target.closest ? e.target.closest(".nte-pin-body") : null;
    if (body && body.__m) { openPopup(e.clientX, e.clientY, body.__m, false); return; }
    var r = world.getBoundingClientRect();
    var s = r.width / world.offsetWidth;
    var x = (e.clientX - r.left) / s, y = (e.clientY - r.top) / s;
    if (x < 0 || y < 0 || x > world.offsetWidth || y > world.offsetHeight) { return; }
    openPopup(e.clientX, e.clientY,
              {x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10, name: "", color: COLORS[0], shape: ""}, true);
  }, true);

  ensure();
  setInterval(ensure, 700);
  requestAnimationFrame(tick);
})();
"""

    MAP_I18N_JS = r"""
(function () {
  if (window.__nteRuRerun) { window.__nteRuRerun(); return; }
  var DICT = __DICT__;
  var ST = {cache: {}, req: {}, pending: [], hide: __HIDE__};
  var SKIP = {SCRIPT: 1, STYLE: 1, TEXTAREA: 1, INPUT: 1, CANVAS: 1, NOSCRIPT: 1, CODE: 1, PRE: 1};
  var ATTRS = ["title", "placeholder", "aria-label", "alt", "data-tooltip"];
  function norm(t) {
    return t.replace(/[\u2018\u2019]/g, "'").replace(/[\u201c\u201d]/g, '"')
            .replace(/\s+/g, " ").trim().toLowerCase();
  }
  var MAP = Object.create(null);
  var LONG = [];
  Object.keys(DICT).forEach(function (k) {
    var n = norm(k);
    MAP[n] = DICT[k];
    if (n.length > 12) { LONG.push([n, DICT[k]]); }
  });
  LONG.sort(function (a, b) { return b[0].length - a[0].length; });
  function mt(text) {
    var key = text.replace(/\s+/g, " ").trim();
    if (key.length < 2 || key.length > 400) { return text; }
    if (!/[A-Za-z]{2}/.test(key) || /[\u0400-\u04FF]/.test(key) || /\d/.test(key)) { return text; }
    if (/:\/\/|^www\.|@[\w-]+\.\w/.test(key)) { return text; }
    var hit = ST.cache[key];
    if (hit !== undefined) {
      var m = text.match(/^(\s*)[\s\S]*?(\s*)$/);
      return (m ? m[1] : "") + hit + (m ? m[2] : "");
    }
    if (!ST.req[key]) { ST.req[key] = 1; ST.pending.push(key); }
    return text;
  }
  function tr(text) {
    if (!text) { return text; }
    var n = norm(text);
    if (!n || /[\u0400-\u04FF]/.test(n)) { return text; }
    if (MAP[n] !== undefined) {
      var m = text.match(/^(\s*)[\s\S]*?(\s*)$/);
      return (m ? m[1] : "") + MAP[n] + (m ? m[2] : "");
    }
    var low = n, out = null;
    for (var i = 0; i < LONG.length; i++) {
      if (low.indexOf(LONG[i][0]) !== -1) {
        out = (out === null ? text : out);
        var esc = LONG[i][0].replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/ /g, "\\s+");
        out = out.replace(new RegExp(esc, "i"), LONG[i][1]);
        low = norm(out);
      }
    }
    if (out === null) {
      var mm = n.match(/^(.*?)(\s*[:\u2013-]?\s*)(\d[\d\s\/.,%]*)$/);
      if (mm && MAP[mm[1]] !== undefined) { return MAP[mm[1]] + mm[2] + mm[3]; }
      return mt(text);
    }
    return out;
  }
  var HIDE_SET = {tasks: 1, quests: 1, achievements: 1, tracker: 1, tools: 1,
                  "задачи": 1, "квесты": 1, "достижения": 1, "трекер": 1, "инструменты": 1,
                  login: 1, signin: 1, logout: 1, signup: 1, "войти": 1, "выйти": 1};
  var HIDDEN = [];
  var WAIT = Object.create(null);     // ОПТИМИЗАЦИЯ: ключ -> узлы, ждущие перевода
  function wait(text, node, attr) {
    var key = text.replace(/\s+/g, " ").trim();
    if (!ST.req[key] || ST.cache[key] !== undefined) { return; }
    if (!attr) {
      if (node.__nteW === key) { return; }
      node.__nteW = key;
    }
    (WAIT[key] = WAIT[key] || []).push([node, attr]);
  }
  function setGone(el) {
    el.__nteDisp = el.style.getPropertyValue("display");
    el.__nteDispPri = el.style.getPropertyPriority("display");
    el.style.setProperty("display", "none", "important");
    HIDDEN.push(el);
  }
  function goneUp(el) {
    el.__nteGone = 1;
    setGone(el);
    var par = el.parentElement;
    while (par && par !== document.body && par !== document.documentElement) {
      var all = true;
      for (var i = 0; i < par.children.length; i++) {
        if (par.children[i].style.getPropertyValue("display") !== "none") { all = false; break; }
      }
      if (!all) { break; }
      par.__nteGone = 1;
      setGone(par);
      par = par.parentElement;
    }
  }
  function bannerText(t) {
    var l = t.toLowerCase();
    return (l.indexOf("viewing as guest") !== -1 || l.indexOf("режиме гостя") !== -1) &&
           (l.indexOf("saved locally") !== -1 || l.indexOf("сохраняется локально") !== -1);
  }
  function isBanner(el) {
    var t = el.textContent || "";
    if (t.length < 30 || t.length > 700 || !bannerText(t)) { return false; }
    for (var i = 0; i < el.children.length; i++) {
      if (bannerText(el.children[i].textContent || "")) { return false; }
    }
    return true;
  }
  function hideTab(el) {
    if (el.__nteGone) { return; }
    var nm = el.nodeName;
    if (nm === "A" && /discord\.(gg|com)/i.test(el.getAttribute("href") || "")) {
      var rd = el.getBoundingClientRect();
      if (rd.height > 0 && rd.top < 260) { goneUp(el); }
      return;
    }
    if (/^(DIV|SECTION|ASIDE|P|HEADER|SPAN)$/.test(nm) && el.children.length <= 10 && isBanner(el)) {
      var rb = el.getBoundingClientRect();
      if (rb.height > 0 && rb.top < 300) { goneUp(el); }
      return;
    }
    if (!/^(A|BUTTON|LI|DIV|SPAN)$/.test(nm)) { return; }
    if (el.children.length > 3) { return; }
    var t = el.textContent || "";
    if (t.length > 30) { return; }
    var key = t.toLowerCase().replace(/[^a-z\u0430-\u044f\u0451]+/g, "");
    if (!HIDE_SET[key]) { return; }
    var r = el.getBoundingClientRect();
    if (r.height <= 0 || r.top > 170) { return; }
    goneUp(el);
  }
  function restoreTabs() {
    HIDDEN.forEach(function (el) {
      el.style.removeProperty("display");
      if (el.__nteDisp) { el.style.setProperty("display", el.__nteDisp, el.__nteDispPri || ""); }
      el.__nteGone = 0;
    });
    HIDDEN = [];
  }
  function doNode(node) {
    if (node.nodeType === 3) {
      var p = node.parentNode;
      if (p && SKIP[p.nodeName]) { return; }
      if (p && p.closest && p.closest("[data-nte-skip]")) { return; }
      var v = node.nodeValue, r = tr(v);
      if (r !== v) { node.nodeValue = r; } else { wait(v, node, null); }
      return;
    }
    if (node.nodeType !== 1 || SKIP[node.nodeName]) { return; }
    if (node.hasAttribute("data-nte-skip")) { return; }
    if (node.classList && node.classList.contains("map-marker")) { return; }
    if (ST.hide && !(node.closest && node.closest(".map-viewport"))) { hideTab(node); }
    for (var i = 0; i < ATTRS.length; i++) {
      var a = node.getAttribute && node.getAttribute(ATTRS[i]);
      if (a) {
        var ra = tr(a);
        if (ra !== a) { node.setAttribute(ATTRS[i], ra); } else { wait(a, node, ATTRS[i]); }
      }
    }
    for (var c = node.firstChild; c; c = c.nextSibling) { doNode(c); }
    if (node.shadowRoot) { doNode(node.shadowRoot); }
  }
  function run(root) {
    try { doNode(root || document.body); } catch (e) {}
  }
  var OPTS = {childList: true, subtree: true, characterData: true, attributes: true,
              attributeFilter: ATTRS};
  var obs = new MutationObserver(function (muts) {
    var seen = [];
    for (var i = 0; i < muts.length; i++) {
      var m = muts[i];
      if (m.type === "childList") {
        for (var j = 0; j < m.addedNodes.length; j++) { seen.push(m.addedNodes[j]); }
      } else { seen.push(m.target); }
    }
    for (var k = 0; k < seen.length; k++) { run(seen[k]); }
    obs.takeRecords();
  });
  function rerun() {
    obs.disconnect();
    run(document.body);
    obs.observe(document.documentElement, OPTS);
  }
  window.__nteRuObserver = obs;
  window.__nteRuRerun = rerun;
  window.__nteRuTake = function () { var a = ST.pending; ST.pending = []; return a; };
  window.__nteRuSetHide = function (flag) {
    ST.hide = !!flag;
    if (ST.hide) { rerun(); } else { restoreTabs(); }
  };
  window.__nteRuApply = function (obj, failed) {
    // ОПТИМИЗАЦИЯ: переводим только узлы, ждавшие эти строки, вместо обхода всего документа
    obs.disconnect();
    Object.keys(obj || {}).forEach(function (k) {
      ST.cache[k] = obj[k];
      var list = WAIT[k];
      if (!list) { return; }
      delete WAIT[k];
      list.forEach(function (it) {
        var n = it[0];
        if (!n.isConnected) { return; }
        if (it[1]) {
          var a = n.getAttribute(it[1]);
          if (a) { var ra = tr(a); if (ra !== a) { n.setAttribute(it[1], ra); } }
        } else {
          n.__nteW = null;
          var v = n.nodeValue, r = tr(v);
          if (r !== v) { n.nodeValue = r; }
        }
      });
    });
    (failed || []).forEach(function (k) {
      delete ST.req[k];
      if (WAIT[k]) { ST.req[k] = 1; ST.pending.push(k); }
    });
    obs.observe(document.documentElement, OPTS);
  };
  rerun();
})();
"""

    MAP_DUMP_JS = (
        "(function(){try{if(location.origin!=='https://nte.stardb.gg')return null;"
        "var o={};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);"
        "o[k]=localStorage.getItem(k);}return JSON.stringify(o);}catch(e){return null;}})()")

    def _map_inject_translation(self, ok: bool = True):
        view = getattr(self, "_map_view", None)
        if not ok or not view:
            return
        try:
            script = self.MAP_I18N_JS.replace(
                "__DICT__", json.dumps(self.MAP_RU_DICT, ensure_ascii=False)).replace(
                "__HIDE__", "true" if getattr(self, "_map_hide_tabs", True) else "false")
            view.page().runJavaScript(script)
            view.page().runJavaScript(self.MAP_MARKS_JS)
            QTimer.singleShot(1200, lambda: view.page().runJavaScript(script))
            QTimer.singleShot(3500, lambda: view.page().runJavaScript(script))
        except Exception:
            pass

    def _map_marks_path(self) -> Path:
        return app_dir() / "map_marks_backup.json"

    def _map_marks_load(self) -> dict:
        try:
            data = json.loads(self._map_marks_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _map_marks_store(self, raw):
        # ОПТИМИЗАЦИЯ: на диск пишем только если localStorage реально изменился
        if not isinstance(raw, str) or raw == getattr(self, "_map_marks_last", None):
            return
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                self._map_marks_path().write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8")
                self._map_marks_last = raw
        except Exception:
            pass

    def _map_marks_autosave_start(self):
        self._map_marks_timer = QTimer(self)
        self._map_marks_timer.setInterval(4000)
        self._map_marks_timer.timeout.connect(self._map_marks_snapshot)
        self._map_marks_timer.start()

    def _map_marks_snapshot(self, force: bool = False):
        # ОПТИМИЗАЦИЯ: пока открыта другая вкладка, localStorage не снимается
        view = getattr(self, "_map_view", None)
        if view and (force is True or self.tabs.currentWidget() is getattr(self, "_map_holder", None)):
            view.page().runJavaScript(self.MAP_DUMP_JS, self._map_marks_store)

    def _map_shutdown(self):
        view = getattr(self, "_map_view", None)
        if not view:
            return
        try:
            from PyQt6.QtCore import QEventLoop
            for name in ("_map_marks_timer", "_map_tr_timer"):
                t = getattr(self, name, None)
                if t:
                    t.stop()
            loop = QEventLoop()
            page = view.page()

            def got(raw):
                self._map_marks_store(raw)
                loop.quit()
            page.runJavaScript(self.MAP_DUMP_JS, got)
            QTimer.singleShot(500, loop.quit)
            loop.exec()
            self._map_view = None
            view.deleteLater()
            page.deleteLater()
        except Exception:
            pass

    def _map_tr_cache_path(self) -> Path:
        return app_dir() / "map_ru_cache.json"

    def _map_tr_setup(self):
        self._map_tr_cache = {}
        self._map_tr_fails = {}
        self._map_tr_busy = False
        try:
            self._map_tr_cache = json.loads(self._map_tr_cache_path().read_text(encoding="utf-8"))
        except Exception:
            self._map_tr_cache = {}
        self._map_tr_bridge = _MapTrBridge(self)
        self._map_tr_bridge.done.connect(self._map_tr_done)
        self._map_tr_timer = QTimer(self)
        self._map_tr_timer.setInterval(600)
        self._map_tr_timer.timeout.connect(self._map_tr_poll)
        self._map_tr_timer.start()

    def _map_tr_poll(self):
        view = getattr(self, "_map_view", None)
        if not view or self._map_tr_busy:
            return
        view.page().runJavaScript(
            "window.__nteRuTake ? window.__nteRuTake() : []", self._map_tr_taken)

    def _map_tr_taken(self, keys):
        if not keys or not isinstance(keys, list):
            return
        ready = {k: self._map_tr_cache[k] for k in keys if k in self._map_tr_cache}
        todo = [k for k in keys if k not in self._map_tr_cache][:80]
        if ready:
            self._map_tr_push(ready, [])
        if not todo:
            return
        self._map_tr_busy = True
        bridge = self._map_tr_bridge

        def work():
            from concurrent.futures import ThreadPoolExecutor
            result, failed = {}, []

            def one(k):
                try:
                    return k, _map_translate_en_ru(k)
                except Exception:
                    return k, None
            try:
                with ThreadPoolExecutor(max_workers=4) as ex:
                    for k, v in ex.map(one, todo):
                        if v:
                            result[k] = v
                        else:
                            failed.append(k)
            finally:
                bridge.done.emit(result, failed)
        import threading
        threading.Thread(target=work, daemon=True).start()

    def _map_tr_push(self, result: dict, failed: list):
        view = getattr(self, "_map_view", None)
        if not view:
            return
        view.page().runJavaScript(
            "window.__nteRuApply && window.__nteRuApply(%s, %s)"
            % (json.dumps(result), json.dumps(failed)))

    def _map_tr_done(self, result: dict, failed: list):
        self._map_tr_busy = False
        retry = []
        for k in failed:
            self._map_tr_fails[k] = self._map_tr_fails.get(k, 0) + 1
            if self._map_tr_fails[k] < 3:
                retry.append(k)
            else:
                self._map_tr_cache[k] = k
                result[k] = k
        if result:
            self._map_tr_cache.update(result)
            try:
                self._map_tr_cache_path().write_text(
                    json.dumps(self._map_tr_cache, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        self._map_tr_push(result, retry)

    def _build_map(self) -> QWidget:
        self._map_holder = QWidget()
        self._map_lay = QVBoxLayout(self._map_holder)
        self._map_lay.setContentsMargins(0, 0, 0, 0)
        self._map_view = None
        self._map_hint = make_label("Загрузка карты…", "hint")
        self._map_lay.addWidget(self._map_hint)
        return self._map_holder

    def _map_set_active(self, on_map: bool):
        """ОПТИМИЗАЦИЯ: таймеры карты (опрос перевода раз в 0,6 с и автосохранение меток)
        работают только пока открыта вкладка «Карта». При уходе с неё метки сохраняются
        один раз."""
        if not getattr(self, "_map_view", None):
            return
        timers = [getattr(self, n, None) for n in ("_map_tr_timer", "_map_marks_timer")]
        if not on_map:
            self._map_marks_snapshot(force=True)
        for t in timers:
            if t is not None:
                t.start() if on_map else t.stop()

    def _init_map_view(self):
        try:
            from PyQt6.QtWebEngineWidgets import QWebEngineView
            from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        except Exception as e:
            # показываем настоящую причину: чаще всего это не «модуля нет», а несовпадение версий
            # PyQt6 / PyQt6-WebEngine (должны быть одной линейки, например все 6.11.x)
            self._map_hint.setText(
                "Не удалось загрузить встроенную карту (QtWebEngine).\n\n"
                f"Причина: {type(e).__name__}: {e}\n\n"
                "Если модуль не установлен: pip install PyQt6-WebEngine\n"
                "Версии PyQt6, PyQt6-Qt6, PyQt6-WebEngine и PyQt6-WebEngine-Qt6 должны быть одной линейки "
                "(см. requirements.txt).\n\nПока карту можно открыть в браузере.")
            self._map_hint.setWordWrap(True)
            btn = QPushButton("Открыть карту в браузере")
            btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.MAP_URL)))
            self._map_lay.addWidget(btn)
            self._map_view = False
            return
        bar = QHBoxLayout()
        for text, slot in (("◀", lambda: self._map_view.back()),
                           ("▶", lambda: self._map_view.forward()),
                           ("⟳", lambda: self._map_view.triggerPageAction(
                               QWebEnginePage.WebAction.ReloadAndBypassCache))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        self._map_hide_tabs = True
        bar.addStretch(1)
        self._map_lay.addLayout(bar)
        # постоянный профиль: отметки на карте (localStorage) сохраняются между запусками
        self._map_profile = QWebEngineProfile("nte_map", self)
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineScript
        # ОПТИМИЗАЦИЯ: кэш на диске (раньше — в памяти + временная папка, удалявшаяся при каждом
        # запуске: картинки карты скачивались заново). Лежит рядом с базой, лимит MAP_CACHE_MAX_MB.
        try:
            import shutil
            for old_dir in Path(tempfile.gettempdir()).glob("nte_map_cache_*"):   # хвосты старой версии
                shutil.rmtree(old_dir, ignore_errors=True)
            cache_dir = Path(self.db.path).parent / "map_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._map_profile.setCachePath(str(cache_dir))
            self._map_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            self._map_profile.setHttpCacheMaximumSize(self.MAP_CACHE_MAX_MB * 1024 * 1024)
        except Exception:
            pass
        try:
            self._map_profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        except Exception:
            pass
        page = QWebEnginePage(self._map_profile, self)
        backup = self._map_marks_load()
        if backup:
            script = QWebEngineScript()
            script.setName("nte_marks_restore")
            script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            script.setRunsOnSubFrames(False)
            script.setSourceCode(
                "(function(){try{if(location.origin!=='https://nte.stardb.gg')return;"
                "var d=%s;for(var k in d){if(localStorage.getItem(k)===null)"
                "{localStorage.setItem(k,d[k]);}}}catch(e){}})();" % json.dumps(backup))
            page.scripts().insert(script)
        self._map_view = QWebEngineView(self._map_holder)
        self._map_view.setPage(page)
        self._map_tr_setup()
        self._map_marks_autosave_start()
        page.loadFinished.connect(self._map_inject_translation)
        self._map_view.setUrl(QUrl(self.MAP_URL))
        self._map_lay.addWidget(self._map_view, 1)
        self._map_hint.hide()
