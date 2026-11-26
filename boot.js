/* Виконується до першого малювання: ставить збережену тему (світла / темна; «авто» — як у системі), щоб сторінка не блимала. */
try { var t = localStorage.getItem('ftup-lib:theme'); if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t); } catch (e) {}
/* Стара сторінка з кешу + новий код після оновлення сайту (26.11.2026: «мобільна версія не завантажується»): якщо до запуску
   застосунку впав скрипт чи код — один раз перезавантажити свіжу сторінку (інша адреса ?r=… оминає кеш). Повторно — лише після успішного запуску. */
window.__ftupReload = function () {
  try {
    if (sessionStorage.getItem('ftup-lib:reloaded')) return false;
    sessionStorage.setItem('ftup-lib:reloaded', '1');
    location.replace(location.pathname + '?r=' + Date.now() + location.hash);
    return true;
  } catch (e) { return false; }
};
window.addEventListener('error', function (e) {
  if (document.documentElement.classList.contains('app-ready')) return;
  var t = e.target, tag = t && t.tagName;
  if (e.error || tag === 'SCRIPT' || (tag === 'LINK' && t.rel === 'stylesheet')) window.__ftupReload();
}, true);
