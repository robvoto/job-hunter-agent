import {
  escapeHtml,
  setToggleChecked,
  getToggleChecked,
} from '../shared/settings-utils.js';

let alertsLabels = null;

function loadAlertsLabels() {
  if (alertsLabels) {
    return alertsLabels;
  }
  const embedded = document.getElementById('settings_alerts_labels_json')?.textContent?.trim();
  if (embedded) {
    alertsLabels = JSON.parse(embedded);
    return alertsLabels;
  }
  if (window.__JOB_HUNTER_SETTINGS_ALERTS_LABELS__) {
    alertsLabels = window.__JOB_HUNTER_SETTINGS_ALERTS_LABELS__;
    return alertsLabels;
  }
  return null;
}

export const JobHunterAlertsSettings = (function () {

  let telegramConnectLink = '';

  function renderTelegramSubscribers(subscribers) {
    const labels = loadAlertsLabels();
    if (!labels) return;
    const panel = document.getElementById('telegram_subscribers_panel');
    if (!panel) return;
    panel.hidden = false;
    if (!subscribers || !subscribers.length) {
      panel.innerHTML = `<p class="panel-copy">${escapeHtml(labels.telegram_subscribers_empty)}</p>`;
      return;
    }
    panel.innerHTML = `
      <p class="panel-copy"><strong>${escapeHtml(labels.telegram_subscribers_label)}</strong></p>
      <ul class="telegram-subscribers-list">
        ${subscribers.map(item => `
          <li>
            ${escapeHtml(item.first_name || item.username || item.chat_id || labels.telegram_user_label)}
            ${item.username ? ` (@${escapeHtml(item.username)})` : ''}
          </li>
        `).join('')}
      </ul>
    `;
  }

  function renderTelegramConnectPanel(settings) {
    const labels = loadAlertsLabels();
    if (!labels) return;
    const panel = document.getElementById('telegram_connect_panel');
    if (!panel) return;
    panel.hidden = false;
    if (!settings?.telegram?.bot_token_present) {
      telegramConnectLink = '';
      panel.innerHTML = `<p class="panel-copy">${escapeHtml(labels.telegram_connect_help_missing)}</p>`;
      return;
    }
    panel.innerHTML = `<p class="panel-copy">${escapeHtml(labels.telegram_connect_help_ready)}</p>`;
  }

  // Fills the alerts/schedule/LLM form. Calls renderLlmModelOptions() from
  // settings-page.js scope (resolved lazily at call time).
  function fillUserSettings(settings) {
    settings = settings || {};
    const schedule = settings.schedule || {};
    const scheduleEl = document.getElementById('schedule_daily_time_local');
    if (scheduleEl) scheduleEl.value = schedule.daily_time_local || '08:30';
    const telegram = settings.telegram || {};
    setToggleChecked('telegram_enabled', Boolean(telegram.enabled));
    const botToken = document.getElementById('telegram_bot_token');
    if (botToken) {
      botToken.value = '';
      botToken.placeholder = telegram.bot_token_present
        ? 'Token saved — enter a new value to replace'
        : '123456:ABC...';
    }
    const botUsername = document.getElementById('telegram_bot_username');
    if (botUsername) botUsername.value = telegram.bot_username || '';
    setToggleChecked('telegram_disable_link_preview', Boolean(telegram.disable_link_preview));
    telegramConnectLink = telegram.bot_username
      ? `https://web.telegram.org/k/#@${telegram.bot_username}`
      : '';
    renderTelegramSubscribers(telegram.subscribers || []);
    renderTelegramConnectPanel(settings);
    // renderLlmModelOptions is defined in settings-page.js; resolved at call time.
    if (typeof renderLlmModelOptions === 'function') renderLlmModelOptions();
  }

  // Collects alerts/schedule/LLM form values. Takes currentUserSettings as
  // baseline so unedited keys are preserved.
  function collectUserSettings(currentUserSettings) {
    const currentSchedule = currentUserSettings?.schedule || {};
    const currentLlmModel = String(
      document.getElementById('llm_model')?.value
      || currentUserSettings?.llm?.model
      || ''
    ).trim();
    return {
      schedule: {
        daily_time_local: document.getElementById('schedule_daily_time_local')?.value || '08:30',
        loop_sleep_seconds: Number(currentSchedule.loop_sleep_seconds || 300),
      },
      telegram: {
        enabled: getToggleChecked('telegram_enabled'),
        bot_token: document.getElementById('telegram_bot_token')?.value.trim(),
        bot_username: document.getElementById('telegram_bot_username')?.value.trim().replace(/^@+/, ''),
        disable_link_preview: getToggleChecked('telegram_disable_link_preview'),
      },
      llm: currentLlmModel ? { model: currentLlmModel } : {},
    };
  }

  function getTelegramConnectLink() {
    return telegramConnectLink;
  }

  async function loadTelegramConnectLink() {
    const response = await jobHunterFetch('/api/telegram/connect-link');
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Could not build Telegram connect link');
    telegramConnectLink = payload.connect_link || '';
    renderTelegramConnectPanel({ telegram: { bot_token_present: true } });
    return payload;
  }

  async function syncTelegramSubscribers() {
    const response = await jobHunterFetch('/api/telegram/sync', { method: 'POST' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Could not refresh the connected Telegram account');
    fillUserSettings(payload.settings || {});
    if (payload.result?.bot_username) {
      telegramConnectLink = `https://web.telegram.org/k/#@${payload.result.bot_username}`;
    }
    renderTelegramConnectPanel(payload.settings || {});
    return payload;
  }

  async function pollForConnection(maxAttempts = 3, intervalMs = 8000) {
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(resolve => setTimeout(resolve, intervalMs));
      let payload;
      try {
        const response = await jobHunterFetch('/api/telegram/sync', { method: 'POST' });
        payload = await response.json().catch(() => ({}));
        if (!response.ok) break;
      } catch {
        break;
      }
      fillUserSettings(payload.settings || {});
      renderTelegramConnectPanel(payload.settings || {});
      const count = payload.settings?.telegram?.subscriber_count || 0;
      if (count > 0) return true;
    }
    return false;
  }

  async function sendTelegramTestMessage() {
    const response = await jobHunterFetch('/api/telegram/test-message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Could not send Telegram test message');
    return payload;
  }

  return {
    fillUserSettings,
    collectUserSettings,
    getTelegramConnectLink,
    loadTelegramConnectLink,
    syncTelegramSubscribers,
    pollForConnection,
    sendTelegramTestMessage,
  };
}());
