(function () {
  const ENHANCED_ATTR = 'data-fit-summary-enhanced';
  const MAX_ITEMS = 5;

  function cleanText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function sentenceCase(value) {
    const text = cleanText(value);
    if (!text) return '';
    return text.charAt(0).toLowerCase() + text.slice(1);
  }

  function phrase(items) {
    const cleaned = Array.from(new Set(items.map(cleanText).filter(Boolean))).slice(0, MAX_ITEMS);
    if (cleaned.length <= 1) return cleaned[0] || '';
    if (cleaned.length === 2) return `${cleaned[0]} and ${cleaned[1]}`;
    return `${cleaned.slice(0, -1).join(', ')}, and ${cleaned[cleaned.length - 1]}`;
  }

  function extractCapabilityFromReason(reason) {
    const text = cleanText(reason);
    const match = text.match(/^The ad asks for (.*?), and your profile shows this experience\.?$/i);
    if (match && match[1]) return cleanText(match[1]);
    return text
      .replace(/^Requirement matched:\s*/i, '')
      .replace(/^The job ad strongly matches your\s*/i, '')
      .replace(/^The job title matches one of your\s*/i, '')
      .replace(/\.$/, '')
      .trim();
  }

  function findGoodFitGroup(card) {
    const groups = Array.from(card.querySelectorAll('.job-insights .job-insight-group'));
    return groups.find((group) => {
      const heading = cleanText(group.querySelector('strong')?.textContent).toLowerCase();
      return heading === 'why this looks like a good fit' || heading === 'why this is a good fit';
    });
  }

  function supportedRequirements(card) {
    return Array.from(card.querySelectorAll('.job-requirement-item--supported .job-requirement-text'))
      .map((node) => cleanText(node.childNodes[0]?.textContent || node.textContent))
      .filter(Boolean);
  }

  function visibleReasons(group) {
    return Array.from(group.querySelectorAll('li')).map((item) => cleanText(item.textContent)).filter(Boolean);
  }

  function buildSummary(card, group) {
    const requirements = supportedRequirements(card);
    if (requirements.length) {
      return `This role looks like a good fit because the ad asks for ${phrase(requirements.map(sentenceCase))}, and your profile shows support for those areas.`;
    }

    const capabilities = visibleReasons(group).map(extractCapabilityFromReason).filter(Boolean);
    if (capabilities.length) {
      return `This role looks like a good fit because the ad asks for ${phrase(capabilities.map(sentenceCase))}, and your profile shows matching experience.`;
    }

    return '';
  }

  function enhanceFitSummaries(root = document) {
    const cards = Array.from(root.querySelectorAll?.('.job-card') || []);
    for (const card of cards) {
      if (card.getAttribute(ENHANCED_ATTR) === '1') continue;
      const group = findGoodFitGroup(card);
      if (!group) continue;

      const summary = buildSummary(card, group);
      if (!summary) continue;

      const heading = group.querySelector('strong');
      if (heading) heading.textContent = 'Why this is a good fit';

      const summaryElement = document.createElement('p');
      summaryElement.className = 'job-fit-summary-copy';
      summaryElement.textContent = summary;
      group.insertBefore(summaryElement, group.querySelector('ul'));
      card.setAttribute(ENHANCED_ATTR, '1');
    }
  }

  window.jobHunterEnhanceFitSummaries = enhanceFitSummaries;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => enhanceFitSummaries());
  } else {
    enhanceFitSummaries();
  }

  const mount = document.getElementById('results-mount') || document.body;
  if (mount && window.MutationObserver) {
    new MutationObserver(() => enhanceFitSummaries(mount)).observe(mount, {
      childList: true,
      subtree: true,
    });
  }
})();
