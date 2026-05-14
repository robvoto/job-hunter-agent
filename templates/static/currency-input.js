(function () {
  function normalizeCurrencyDigits(value) {
    return String(value ?? '').replace(/[^\d]/g, '').trim();
  }

  function formatCurrencyValue(value) {
    const digits = normalizeCurrencyDigits(value);
    if (!digits) return '';
    return Number(digits).toLocaleString('en-AU');
  }

  function parseCurrencyValue(value) {
    const digits = normalizeCurrencyDigits(value);
    return digits ? Number(digits) : '';
  }

  function setCurrencyInputValue(input, value) {
    if (!input) return;
    const formatted = formatCurrencyValue(value);
    input.value = formatted;
  }

  function bindCurrencyInput(input) {
    if (!input) return;
    const sync = () => {
      input.value = formatCurrencyValue(input.value);
    };
    input.addEventListener('input', sync);
    input.addEventListener('blur', sync);
    sync();
  }

  window.JobHunterCurrencyUi = {
    formatCurrencyValue,
    parseCurrencyValue,
    setCurrencyInputValue,
    bindCurrencyInput,
  };
})();
