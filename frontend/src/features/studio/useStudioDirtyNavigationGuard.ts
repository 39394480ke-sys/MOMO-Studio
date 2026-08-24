import { useEffect } from 'react';

interface UseStudioDirtyNavigationGuardOptions {
  formalDirty: boolean;
  persistWorkspace: () => Promise<unknown>;
}

export function useStudioDirtyNavigationGuard({
  formalDirty,
  persistWorkspace,
}: UseStudioDirtyNavigationGuardOptions): void {
  useEffect(() => {
    const prompt = 'This draft is autosaved, but its Motion changes are not saved. Leave Studio?';
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!formalDirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    const guardLinks = (event: MouseEvent) => {
      if (!formalDirty || event.defaultPrevented || event.button !== 0) return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const link = target.closest('a[href]');
      if (!(link instanceof HTMLAnchorElement)) return;
      if (link.origin !== window.location.origin || link.target === '_blank' || link.hasAttribute('download')) return;
      if (link.href === window.location.href) return;
      if (window.confirm(prompt)) {
        void persistWorkspace().catch(() => undefined);
        return;
      }
      event.preventDefault();
      event.stopPropagation();
    };
    let restoringPopstate = false;
    const protectedIndex = (
      typeof window.history.state?.idx === 'number' ? window.history.state.idx : 0
    );
    const guardPopstate = (event: PopStateEvent) => {
      if (!formalDirty) return;
      if (restoringPopstate) {
        restoringPopstate = false;
        return;
      }
      if (!window.confirm(prompt)) {
        restoringPopstate = true;
        const nextIndex = typeof event.state?.idx === 'number' ? event.state.idx : protectedIndex - 1;
        const restoreDelta = protectedIndex - nextIndex;
        window.history.go(restoreDelta === 0 ? 1 : restoreDelta);
      }
    };
    window.addEventListener('beforeunload', beforeUnload);
    window.addEventListener('popstate', guardPopstate);
    document.addEventListener('click', guardLinks, true);
    return () => {
      window.removeEventListener('beforeunload', beforeUnload);
      window.removeEventListener('popstate', guardPopstate);
      document.removeEventListener('click', guardLinks, true);
    };
  }, [formalDirty, persistWorkspace]);
}
