import {
  escapeHtml,
  setToggleChecked,
  getToggleChecked,
  syncSourcePanelDisabledState,
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
  let scheduleStatusRequestId = 0;

  function setAgentTokenStatus(message = '') {
    const panel = document.getElementById('agent_tokens_status');
    if (panel) panel.textContent = message;
  }

  function formatAgentTokenCreatedAt(value) {
    const parsed = new Date(String(value || '').trim());
    if (Number.isNaN(parsed.getTime())) return '';
    return parsed.toLocaleString([], {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function renderAgentTokens(tokens) {
    const labels = loadAlertsLabels();
    const panel = document.getElementById('agent_tokens_list');
    if (!labels || !panel) return;
    const active = Array.isArray(tokens) ? tokens.filter(token => !token?.revoked_at) : [];
    if (!active.length) {
      panel.innerHTML = `<p class="panel-copy">${escapeHtml(labels.agent_tokens_empty)}</p>`;
      return;
    }
    panel.innerHTML = `<ul>${active.map((token) => {
      const label = String(token?.label || '').trim();
      const agentId = String(token?.agent_id || '').trim();
      const createdAt = formatAgentTokenCreatedAt(token?.created_at);
      const created = createdAt
        ? labels.agent_tokens_created_template.replace('{date}', createdAt)
        : '';
      return `
        <li>
          <strong>${escapeHtml(label)}</strong>
          ${agentId ? `<span>${escapeHtml(agentId)}</span>` : ''}
          ${created ? `<span>${escapeHtml(created)}</span>` : ''}
          <button
            class="jh-button jh-button--danger jh-button--compact"
            type="button"
            data-revoke-agent-token="${escapeHtml(String(token?.token_id || ''))}"
          >${escapeHtml(labels.agent_tokens_revoke_label)}</button>
        </li>`;
    }).join('')}</ul>`;
  }

  async function loadAgentTokens() {
    const labels = loadAlertsLabels();
    if (!labels || !document.getElementById('agent_tokens_panel')) return;
    const response = await jobHunterFetch('/api/agent-tokens', { method: 'GET' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || labels.agent_tokens_load_error);
    renderAgentTokens(payload.tokens || []);
  }

  async function generateAgentToken() {
    const labels = loadAlertsLabels();
    if (!labels) return;
    const response = await jobHunterFetch('/api/agent-tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: 'chatgpt', label: labels.agent_tokens_plan_label }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || labels.agent_tokens_create_error);
    const secretShell = document.getElementById('agent_token_secret_shell');
    const secret = document.getElementById('agent_token_secret');
    if (secretShell && secret) {
      secret.value = String(payload.token || '');
      secretShell.hidden = false;
    }
    setAgentTokenStatus('');
    await loadAgentTokens();
  }

  async function revokeAgentToken(tokenId) {
    const labels = loadAlertsLabels();
    if (!labels) return;
    const response = await jobHunterFetch(`/api/agent-tokens/${encodeURIComponent(tokenId)}`, {
      method: 'DELETE',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || labels.agent_tokens_revoke_error);
    await loadAgentTokens();
  }

  async function copyAgentToken() {
    const labels = loadAlertsLabels();
    const secret = document.getElementById('agent_token_secret');
    if (!labels || !secret?.value) return;
    try {
      await navigator.clipboard.writeText(secret.value);
      setAgentTokenStatus(labels.agent_tokens_copied);
    } catch {
      secret.focus();
      secret.select();
      setAgentTokenStatus(labels.agent_tokens_copy_error);
    }
  }

  function applyAgentTokenLabels() {
    const labels = loadAlertsLabels();
    if (!labels) return;
    const values = {
      agent_tokens_heading: labels.agent_tokens_heading,
      agent_tokens_copy: labels.agent_tokens_copy,
      agent_token_secret_label: labels.agent_tokens_secret_label,
      agent_token_secret_help: labels.agent_tokens_secret_help,
      generate_agent_token: labels.agent_tokens_generate_label,
      copy_agent_token: labels.agent_tokens_copy_label,
    };
    Object.entries(values).forEach(([id, value]) => {
      const element = document.getElementById(id);
      if (element) element.textContent = value;
    });
  }

  function formatScheduleDateTime(value) {
    const parsed = new Date(String(value || '').trim());
    if (Number.isNaN(parsed.getTime())) return '';
    return parsed.toLocaleString([], {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  function renderScheduleStatus(settings, payload) {
    const panel = document.getElementById('schedule_runtime_status');
    const labels = loadAlertsLabels();
    if (!panel || !labels) return;
    const scheduleEnabled = Boolean(settings?.schedule?.enabled);
    const scheduler = payload?.scheduler || null;
    if (!scheduleEnabled) {
      panel.dataset.state = 'stopped';
      panel.textContent = labels.schedule_status_off;
      return;
    }
    if (!scheduler?.active) {
      panel.dataset.state = 'unknown';
      panel.textContent = labels.schedule_status_unavailable;
      return;
    }
    const nextRun = formatScheduleDateTime(scheduler.next_run_at);
    if (!nextRun) {
      panel.dataset.state = 'unknown';
      panel.textContent = labels.schedule_status_unavailable;
      return;
    }
    panel.dataset.state = 'running';
    panel.textContent = labels.schedule_status_next_run_template.replace('{next_run}', nextRun);
  }

  async function refreshScheduleStatus(settings) {
    const requestId = ++scheduleStatusRequestId;
    const panel = document.getElementById('schedule_runtime_status');
    const labels = loadAlertsLabels();
    if (panel && labels) {
      panel.dataset.state = 'unknown';
      panel.textContent = labels.schedule_status_checking;
    }
    try {
      const response = await jobHunterFetch('/api/run-status', { method: 'GET' });
      if (!response.ok) throw new Error('Could not load scheduler status');
      const payload = await response.json().catch(() => ({}));
      if (requestId !== scheduleStatusRequestId) return;
      renderScheduleStatus(settings, payload);
    } catch {
      if (requestId !== scheduleStatusRequestId || !panel || !labels) return;
      panel.dataset.state = 'unknown';
      panel.textContent = labels.schedule_status_unavailable;
    }
  }

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
    setToggleChecked('schedule_enabled', Boolean(schedule.enabled));
    syncSourcePanelDisabledState('schedule_enabled');
    const scheduleEl = document.getElementById('schedule_daily_time_local');
    if (scheduleEl) scheduleEl.value = schedule.daily_time_local || '08:30';
    void refreshScheduleStatus(settings);
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
        enabled: getToggleChecked('schedule_enabled'),
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

  function initEventHandlers() {
    const labels = loadAlertsLabels();
    document.getElementById('schedule_enabled')?.addEventListener('change', () => {
      syncSourcePanelDisabledState('schedule_enabled');
    });
    applyAgentTokenLabels();
    void loadAgentTokens().catch(() => {
      if (labels) setAgentTokenStatus(labels.agent_tokens_load_error);
    });
    document.getElementById('generate_agent_token')?.addEventListener('click', async (event) => {
      const button = event.currentTarget;
      if (!labels) return;
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = labels.agent_tokens_generating_label;
      try {
        await generateAgentToken();
      } catch (error) {
        setAgentTokenStatus(error?.message || labels.agent_tokens_create_error);
      } finally {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
    document.getElementById('copy_agent_token')?.addEventListener('click', () => {
      void copyAgentToken();
    });
    document.getElementById('agent_tokens_list')?.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-revoke-agent-token]');
      if (!button || !labels) return;
      const tokenId = String(button.dataset.revokeAgentToken || '').trim();
      if (!tokenId) return;
      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = labels.agent_tokens_revoking_label;
      try {
        await revokeAgentToken(tokenId);
      } catch (error) {
        setAgentTokenStatus(error?.message || labels.agent_tokens_revoke_error);
        button.disabled = false;
        button.textContent = originalLabel;
      }
    });
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
    initEventHandlers,
    getTelegramConnectLink,
    loadTelegramConnectLink,
    syncTelegramSubscribers,
    pollForConnection,
    sendTelegramTestMessage,
  };
}());
