import {
  escapeHtml,
  setToggleChecked,
  getToggleChecked,
} from '../shared/settings-utils.js';

export const JobHunterAlertsSettings = (function () {

  let telegramConnectLink = '';

  function renderTelegramSubscribers(subscribers) {
    const panel = document.getElementById('telegram_subscribers_panel');
    if (!panel) return;
    if (!subscribers || !subscribers.length) {
      panel.innerHTML = '<p class="field-help">You haven\'t linked a Telegram account to receive alerts yet.</p>';
      return;
    }
    panel.innerHTML = `
      <p><strong>Job alerts are currently being sent to:</strong></p>
      <ul style="margin-top: 8px;">
        ${subscribers.map(item => `
          <li>
            ${escapeHtml(item.first_name || item.username || item.chat_id || 'Telegram user')}
            ${item.username ? ` (@${escapeHtml(item.username)})` : ''}
          </li>
        `).join('')}
      </ul>
    `;
  }

  function renderTelegramConnectPanel(settings) {
    const panel = document.getElementById('telegram_connect_panel');
    if (!panel) return;
    const renderConnectHelp = (bodyHtml) => `
      <details class="help-drawer">
        <summary>Connect your Telegram account</summary>
        <div class="help-box">${bodyHtml}</div>
      </details>
    `;
    if (!settings?.telegram?.bot_token_present) {
      telegramConnectLink = '';
      panel.innerHTML = renderConnectHelp(`
        <p class="field-help">Save the bot token and username to unlock the connect link.</p>
      `);
      return;
    }
    if (!telegramConnectLink) {
      panel.innerHTML = renderConnectHelp(`
        <p class="field-help">Open the connect link in Telegram, press <strong>Start</strong>, then refresh the connection here.</p>
      `);
      return;
    }
    panel.innerHTML = renderConnectHelp(`
      <div class="help">Telegram link: <a href="${escapeHtml(telegramConnectLink)}" target="_blank" rel="noreferrer" style="word-break: break-all;">${escapeHtml(telegramConnectLink)}</a></div>
      <p class="field-help" style="margin-top: 10px;">Open it in Telegram, press Start once, then use Refresh Telegram Connection.</p>
    `);
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
    if (botToken) botToken.value = '';
    const botUsername = document.getElementById('telegram_bot_username');
    if (botUsername) botUsername.value = telegram.bot_username || '';
    setToggleChecked('telegram_disable_link_preview', Boolean(telegram.disable_link_preview));
    telegramConnectLink = telegram.bot_username
      ? `https://t.me/${telegram.bot_username}?start=connect`
      : telegramConnectLink;
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
      telegramConnectLink = `https://t.me/${payload.result.bot_username}?start=connect`;
    }
    renderTelegramConnectPanel(payload.settings || {});
    showStatus(payload.message || 'Connected Telegram account refreshed.', 'success');
    return payload;
  }

  async function sendTelegramTestMessage() {
    const response = await jobHunterFetch('/api/telegram/test-message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || 'Could not send Telegram test message');
    showStatus(payload.message || 'Telegram test message sent.', 'success');
    return payload;
  }

  return {
    fillUserSettings,
    collectUserSettings,
    getTelegramConnectLink,
    loadTelegramConnectLink,
    syncTelegramSubscribers,
    sendTelegramTestMessage,
  };
}());
