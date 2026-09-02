export async function confirmRoleFamily(title) {
  const original = String(title || '').replace(/\s+/g, ' ').trim();
  if (!original) return '';

  const response = await jobHunterFetch('/api/profile/resolve-role-family', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: original }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || 'Could not resolve this role family.');
  }
  const family = String(payload.role_family || '').replace(/\s+/g, ' ').trim();
  if (!family) {
    throw new Error('This role could not be resolved confidently. Enter the role family you want to search.');
  }
  if (family.toLowerCase() === original.toLowerCase()) return original;
  if (!window.confirm(`Use “${family}” as your role preference for “${original}”?`)) return '';
  return family;
}
