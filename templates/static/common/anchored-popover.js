// Shared positioning/controller for lightweight, non-modal popovers anchored to an existing control.
function readPixelToken(element, tokenName) {
  const value = Number.parseFloat(getComputedStyle(element).getPropertyValue(tokenName));
  if (!Number.isFinite(value)) {
    throw new Error(`Missing or invalid ${tokenName} token for anchored popover.`);
  }
  return value;
}

export function createAnchoredPopover({ popover, anchor }) {
  if (!(popover instanceof HTMLElement)) {
    throw new Error('Anchored popover requires a valid popover element.');
  }
  if (!(anchor instanceof HTMLElement)) {
    throw new Error('Anchored popover requires a valid anchor element.');
  }
  if (popover.popover !== 'auto' || typeof popover.showPopover !== 'function') {
    throw new Error('Anchored popover requires native popover="auto" support.');
  }

  const isOpen = () => popover.matches(':popover-open');

  const position = () => {
    if (!isOpen()) return;

    const offset = readPixelToken(popover, '--choice-detail-popover-offset');
    const viewportPadding = readPixelToken(popover, '--choice-detail-popover-viewport-padding');
    const anchorRect = anchor.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();

    const maxLeft = Math.max(viewportPadding, window.innerWidth - popoverRect.width - viewportPadding);
    const left = Math.min(Math.max(anchorRect.left, viewportPadding), maxLeft);

    const belowTop = anchorRect.bottom + offset;
    const aboveTop = anchorRect.top - popoverRect.height - offset;
    const fitsBelow = belowTop + popoverRect.height <= window.innerHeight - viewportPadding;
    const top = fitsBelow || aboveTop < viewportPadding ? belowTop : aboveTop;

    popover.style.left = `${Math.round(left)}px`;
    popover.style.top = `${Math.round(Math.max(viewportPadding, top))}px`;
  };

  const show = () => {
    if (!isOpen()) {
      popover.showPopover();
    }
    window.requestAnimationFrame(position);
  };

  const hide = () => {
    if (isOpen()) {
      popover.hidePopover();
    }
  };

  const repositionIfOpen = () => position();
  window.addEventListener('resize', repositionIfOpen);
  window.addEventListener('scroll', repositionIfOpen, true);
  popover.addEventListener('toggle', () => {
    anchor.setAttribute('aria-expanded', String(isOpen()));
    if (isOpen()) {
      position();
    }
  });

  anchor.setAttribute('aria-expanded', 'false');

  return Object.freeze({ show, hide, isOpen, position });
}

// A selected choice already represents the current value, so its next click opens
// the related detail popover. A second click while open retains normal toggle behaviour.
export function bindSelectedChoicePopover({ controller, anchor, input }) {
  if (!controller || !(anchor instanceof HTMLElement) || !(input instanceof HTMLInputElement)) {
    throw new Error('Selected-choice popover binding requires a controller, anchor and input.');
  }

  anchor.addEventListener('click', (event) => {
    if (input.checked && !controller.isOpen()) {
      event.preventDefault();
      controller.show();
    }
  });
}
