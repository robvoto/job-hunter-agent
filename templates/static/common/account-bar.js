(function () {
  function initAccountBar() {
    var userMenu = document.getElementById('job_hunter_account_user_menu');
    var avatarButton = document.getElementById('job_hunter_account_avatar_btn');
    var userDropdown = document.getElementById('job_hunter_account_dropdown');
    var testPanel = document.getElementById('job_hunter_account_test_panel');
    var testTrigger = document.getElementById('job_hunter_account_test_trigger');
    var testMenu = document.getElementById('job_hunter_account_test_menu');

    function setUserMenuOpen(open) {
      if (!avatarButton || !userDropdown) return;
      userDropdown.hidden = !open;
      avatarButton.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    function setTestMenuOpen(open) {
      if (!testTrigger || !testMenu) return;
      testMenu.classList.toggle('is-open', Boolean(open));
      testTrigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    if (avatarButton && userDropdown) {
      avatarButton.addEventListener('click', function (event) {
        event.stopPropagation();
        setUserMenuOpen(userDropdown.hidden);
        setTestMenuOpen(false);
      });
    }

    if (testTrigger && testMenu) {
      testTrigger.addEventListener('click', function (event) {
        event.stopPropagation();
        setTestMenuOpen(!testMenu.classList.contains('is-open'));
        setUserMenuOpen(false);
      });
    }

    document.addEventListener('click', function (event) {
      var target = event.target;
      if (userMenu && !userMenu.contains(target)) {
        setUserMenuOpen(false);
      }
      if (testPanel && !testPanel.contains(target)) {
        setTestMenuOpen(false);
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      if (userDropdown && !userDropdown.hidden) {
        setUserMenuOpen(false);
        if (avatarButton) avatarButton.focus();
      }
      if (testMenu && testMenu.classList.contains('is-open')) {
        setTestMenuOpen(false);
        if (testTrigger) testTrigger.focus();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAccountBar);
  } else {
    initAccountBar();
  }
}());
