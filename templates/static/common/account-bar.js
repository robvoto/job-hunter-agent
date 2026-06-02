/**
 * @file account-bar.js
 * @description Account bar toggle, test-actions menu, and test-action button wiring.
 *   Loaded as a module on every page. Handles both the user-avatar dropdown and the
 *   debug-mode "TEST ACTIONS" menu. Test action handlers live here (not in settings-page.js)
 *   so they work on every page, not just Settings.
 * @author hernanvoto
 * @created 2026-05-27
 */

// jobHunterFetch is a global set by csrf.js, which loads before this module.
/* global jobHunterFetch */

function initAccountBar() {
  const userMenu = document.getElementById('job_hunter_account_user_menu');
  const avatarButton = document.getElementById('job_hunter_account_avatar_btn');
  const userDropdown = document.getElementById('job_hunter_account_dropdown');
  const testPanel = document.getElementById('job_hunter_account_test_panel');
  const testTrigger = document.getElementById('job_hunter_account_test_trigger');
  const testMenu = document.getElementById('job_hunter_account_test_menu');
  const resetUserBtn = document.getElementById('job_hunter_reset_user_btn');

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
    avatarButton.addEventListener('click', (event) => {
      event.stopPropagation();
      setUserMenuOpen(userDropdown.hidden);
      setTestMenuOpen(false);
    });
  }

  if (testTrigger && testMenu) {
    testTrigger.addEventListener('click', (event) => {
      event.stopPropagation();
      setTestMenuOpen(!testMenu.classList.contains('is-open'));
      setUserMenuOpen(false);
    });
  }

  document.addEventListener('click', (event) => {
    if (userMenu && !userMenu.contains(event.target)) setUserMenuOpen(false);
    if (testPanel && !testPanel.contains(event.target)) setTestMenuOpen(false);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (userDropdown && !userDropdown.hidden) {
      setUserMenuOpen(false);
      avatarButton?.focus();
    }
    if (testMenu && testMenu.classList.contains('is-open')) {
      setTestMenuOpen(false);
      testTrigger?.focus();
    }
  });

  // Test action buttons are wired here so they work on every page, not just Settings.
  if (resetUserBtn) {
    const testLabels = window.__JOB_HUNTER_ONBOARDING_FLOW_LABELS__ || {};
    let resetUserInFlight = false;

    function postTestAction(path) {
      return jobHunterFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
    }

    resetUserBtn?.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (resetUserInFlight) return;
      const confirmed = window.confirm(
        [testLabels.reset_user_confirm_title, testLabels.reset_user_confirm_body_1, testLabels.reset_user_confirm_body_2]
          .filter(Boolean).join('\n\n')
      );
      if (!confirmed) return;
      try {
        resetUserInFlight = true;
        resetUserBtn.disabled = true;
        const resp = await postTestAction('/api/test/reset-user');
        const payload = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(payload.error || testLabels.reset_user_error || 'Error');
        window.location.href = payload.redirect_to || '/start';
      } catch (err) {
        window.alert(err.message || testLabels.reset_user_error || 'Reset failed');
      } finally {
        resetUserInFlight = false;
        resetUserBtn.disabled = false;
      }
    });
  }
}

// Modules are deferred — DOM is parsed by the time this runs.
initAccountBar();
