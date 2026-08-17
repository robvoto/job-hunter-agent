/**
 * @file theme-switcher.js
 * @description Applies the user's saved theme immediately on load (preventing FOUC) and
 *   wires the theme-picker <select> after DOM ready.
 *
 *   NOT an ES module: ES modules are deferred by default. Deferring this script would
 *   cause a flash of unstyled content because the theme would not be applied until after
 *   HTML parsing completes. The synchronous IIFE execution is the intentional design.
 *   Do not convert to type="module" without solving FOUC separately (e.g. an inline
 *   <script> in <head> that applies the theme before this file loads).
 *
 * @author hernanvoto
 * @created 2026-05-27
 */
(function () {
  var KEY = 'jha-theme';
  var THEMES = ['soft-professional', 'bold-aggressive', 'dark-professional'];
  var DEFAULT = 'soft-professional';

  function apply(theme) {
    if (!THEMES.includes(theme)) theme = DEFAULT;
    document.documentElement.setAttribute('data-theme', theme);
  }

  // Apply immediately to prevent flash of unstyled content.
  apply(localStorage.getItem(KEY) || DEFAULT);

  document.addEventListener('DOMContentLoaded', function () {
    apply(localStorage.getItem(KEY) || DEFAULT);
    var sel = document.getElementById('theme_picker');
    if (sel) {
      sel.value = localStorage.getItem(KEY) || DEFAULT;
      sel.addEventListener('change', function () {
        localStorage.setItem(KEY, sel.value);
        apply(sel.value);
      });
    }
  });
}());
