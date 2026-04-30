(function () {
  var KEY = 'jha-theme';
  var THEMES = ['soft-professional', 'bold-aggressive', 'dark-professional'];
  var DEFAULT = 'dark-professional';

  function apply(theme) {
    if (!THEMES.includes(theme)) theme = DEFAULT;
    document.documentElement.setAttribute('data-theme', theme);
  }

  // Apply immediately to prevent flash of unstyled content
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
