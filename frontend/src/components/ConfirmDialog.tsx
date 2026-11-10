import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { Button } from './Button';
import './ConfirmDialog.css';

/**
 * 확인 대화상자. PrivacySettingsPage 의 대화상자와 같은 규칙(열릴 때 첫 컨트롤에 포커스, Tab 순환,
 * Esc 닫기, 닫으면 원래 위치로 포커스 복귀, 처리 중에는 닫기·확인 불가)을 공용으로 옮긴 것입니다.
 */
export function ConfirmDialog({ title, children, confirmLabel, pending, confirmDisabled = false, onConfirm, onClose }: {
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  pending: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    box.current?.querySelector<HTMLElement>('select, textarea, input, button')?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && !pending) { event.preventDefault(); onClose(); return; }
    if (event.key !== 'Tab') return;
    const controls = box.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), select:not(:disabled), textarea:not(:disabled), input:not(:disabled)');
    if (!controls?.length) { event.preventDefault(); box.current?.focus(); return; }
    const first = controls[0]!;
    const last = controls[controls.length - 1]!;
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  return (
    <div className="confirm-overlay">
      <div ref={box} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}
        aria-busy={pending} tabIndex={-1} onKeyDown={onKeyDown}>
        <h2 id={titleId}>{title}</h2>
        {children}
        <div className="confirm-dialog__actions">
          <Button variant="outline" onClick={onClose} disabled={pending}>취소</Button>
          <Button onClick={onConfirm} disabled={pending || confirmDisabled}>
            {pending ? '처리 중…' : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
