import { useEffect, useId, useRef } from 'react';
import type { RefObject } from 'react';
import { createPortal } from 'react-dom';
import type { RecommendationItem, RecommendationRun } from '../api/recommendations';
import { Button } from './Button';
import {
  FEEDBACK_USAGE_NOTE,
  formatModelVersion,
  generatedAtFormat,
  recommendationStatusLabels,
} from './recommendationLabels';
import './RecommendationExplanationDialog.css';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

type RecommendationExplanationDialogProps = {
  item: RecommendationItem;
  run: RecommendationRun;
  onClose: () => void;
  /** 닫힌 뒤 초점을 돌려줄 요소(대화상자를 연 버튼) */
  returnFocusRef: RefObject<HTMLElement | null>;
};

/**
 * 추천 설명 대화상자 (F-018, UI-017). 추천 이유·계산 기준·점수 의미·부족 역량 안내를 보여줍니다.
 * - 열리면 닫기 버튼으로 초점을 옮기고, Tab 은 대화상자 안에서만 돕니다. Esc·바깥 클릭·닫기로 닫힙니다.
 *   키 처리는 document 에 걸어 두어, 안쪽 글자를 눌러 초점이 대화상자 밖(body)으로 나가도 Esc·Tab 가두기가 유지됩니다.
 *   대화상자 자체도 tabIndex=-1 이라 안쪽을 누르면 초점이 대화상자에 머뭅니다.
 * - 닫히면 대화상자를 연 버튼으로 초점을 돌려줍니다.
 * - 부족 역량은 RecommendationItem 계약에 항목이 없으므로 만들어 내지 않고 "추후 제공" 상태로 표시합니다.
 */
export function RecommendationExplanationDialog({ item, run, onClose, returnFocusRef }: RecommendationExplanationDialogProps) {
  const titleId = useId();
  const descriptionId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  // 열려 있는 동안 대화상자 밖(앱 화면)을 inert 로 막아 보조기기·키보드가 배경에 닿지 않게 합니다.
  // 아래 초점 effect 보다 먼저 선언해, 닫힐 때 inert 를 먼저 풀고 나서 여는 버튼으로 초점을 돌려줍니다.
  useEffect(() => {
    const backdrop = dialogRef.current?.parentElement;
    const others = Array.from(document.body.children).filter(
      (element) => element !== backdrop && !element.hasAttribute('inert'),
    );
    others.forEach((element) => element.setAttribute('inert', ''));
    return () => others.forEach((element) => element.removeAttribute('inert'));
  }, []);

  useEffect(() => {
    closeRef.current?.focus();
    const opener = returnFocusRef.current;
    return () => opener?.focus();
  }, [returnFocusRef]);

  // 최신 onClose 를 document 리스너에서 쓰기 위해 ref 로 둡니다(리스너를 매번 다시 걸지 않도록).
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusables = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (!first || !last) return;
      const active = document.activeElement;
      // 초점이 대화상자 밖(body 등)이나 대화상자 자체에 있으면 안쪽 처음/마지막 요소로 되돌립니다.
      if (!(active instanceof HTMLElement) || active === dialog || !dialog.contains(active)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  const personalized = run.status === 'completed';
  const title = item.job_posting.title;

  return createPortal(
    <div
      className="recommendation-dialog-backdrop"
      data-testid="recommendation-dialog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="recommendation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
      >
        <header className="recommendation-dialog-head">
          <h2 id={titleId}>{title} 추천 설명</h2>
          <button ref={closeRef} type="button" className="recommendation-dialog-close" onClick={onClose} aria-label="추천 설명 닫기">
            ×
          </button>
        </header>

        <p id={descriptionId} className="recommendation-dialog-notice">
          이 설명은 목표 직무·보유 기술과 공고 요구를 비교한 참고용 정보이며, AI의 확정 판단이 아닙니다. 공고 내용을 직접 확인해 주세요.
        </p>

        <dl className="recommendation-dialog-facts">
          <div>
            <dt>추천 상태</dt>
            <dd>{recommendationStatusLabels[run.status]}</dd>
          </div>
          <div>
            <dt>계산 기준</dt>
            <dd>{formatModelVersion(run.model_version)}</dd>
          </div>
          <div>
            <dt>생성 시각</dt>
            <dd>
              <time dateTime={run.generated_at}>{generatedAtFormat.format(new Date(run.generated_at))}</time>
            </dd>
          </div>
          <div>
            <dt>적합 점수</dt>
            <dd>{item.score === null ? '점수 없음' : `${item.score} / 100`}</dd>
          </div>
        </dl>

        {!personalized && (
          <p className="recommendation-dialog-fallback" role="note">
            기준 추천(개인화 아님)입니다. 맞춤 추천을 준비하지 못해 최근 게시된 공고를 보여 드리며, 개인 적합 점수를 계산하지 않았습니다.
          </p>
        )}

        <section className="recommendation-dialog-section" aria-label={personalized ? '추천 이유' : '표시 이유'}>
          <h3>{personalized ? '추천 이유' : '표시 이유'}</h3>
          <p>{item.reason}</p>
          {item.score !== null && (
            <p className="recommendation-dialog-muted">
              적합 점수는 0~100 참고 값이며 합격 가능성(확률)이 아닙니다.
            </p>
          )}
        </section>

        <section className="recommendation-dialog-section" aria-label="부족 역량">
          <h3>부족 역량</h3>
          <p className="recommendation-dialog-muted">
            부족 역량 정보 없음 — 추천 결과에 부족 역량 항목이 아직 제공되지 않습니다(추후 제공 예정). 위의 이유만 참고해 주세요.
          </p>
        </section>

        <p className="recommendation-dialog-muted">{FEEDBACK_USAGE_NOTE}</p>

        <footer className="recommendation-dialog-foot">
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
