export function normalizeCurrencyDigits(value) {
  return String(value ?? '').replace(/[^\d]/g, '').trim();
}

export function formatCurrencyValue(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  const digits = normalizeCurrencyDigits(value);
  if (!digits) return '0';
  return Number(digits).toLocaleString('en-AU');
}

export function parseCurrencyValue(value) {
  const digits = normalizeCurrencyDigits(value);
  return digits ? Number(digits) : '';
}

export function setCurrencyInputValue(input, value) {
  if (!input) return;
  const formatted = formatCurrencyValue(value);
  input.value = formatted;
}

export function bindCurrencyInput(input) {
  if (!input) return;
  const sync = () => {
    input.value = formatCurrencyValue(input.value);
  };
  input.addEventListener('input', sync);
  input.addEventListener('blur', sync);
  sync();
}
