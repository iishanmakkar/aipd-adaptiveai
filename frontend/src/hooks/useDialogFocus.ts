import { useEffect } from 'react';
import type { RefObject } from 'react';

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled])',
  'select:not([disabled])', 'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Own focus for an opened surface: move it in when the surface opens, and give
 * focus back to whatever opened it when it closes. With `modal` it also keeps
 * Tab inside while it is up.
 *
 * Modal trapping is what `aria-modal="true"` promises. Without it a keyboard or
 * screen-reader user tabs straight out of the dialog into the page behind it -
 * and on a phone-sized screen they cannot click their way back. A non-modal
 * disclosure (the accessibility toolbar) must NOT trap: it sits inline, and the
 * rest of the page stays usable while it is open.
 */
export function useDialogFocus(
  open: boolean,
  containerRef: RefObject<HTMLElement>,
  modal = true,
) {
  useEffect(() => {
    const container = containerRef.current;
    if (!open || !container) return;

    const opener = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE));
    const items = focusables();
    if (items.length) items[0]?.focus();
    else {
      container.tabIndex = -1;
      container.focus();
    }

    function onKeyDown(event: KeyboardEvent) {
      if (!modal || event.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const outside = !container || !container.contains(active);
      if (outside) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
        return;
      }
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first?.focus();
      }
    }

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      // Only hand focus back if focus is still inside (or on body).
      const active = document.activeElement;
      if (opener && document.contains(opener) && (active === document.body || (container && container.contains(active)))) opener.focus();
    };
  }, [open, containerRef, modal]);
}
