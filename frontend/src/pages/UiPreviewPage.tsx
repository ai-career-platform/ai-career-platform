import { useState } from 'react';
import { FormPreview } from './FormPreview';
import { StatePanel } from '../components/StatePanel';
import { TextField } from '../components/TextField';
import { LandingComponentsPreview } from './LandingComponentsPreview';
import { TablePreview } from './TablePreview';

export function UiPreviewPage() {
  const [retryCount, setRetryCount] = useState(0);

  return (
    <section aria-labelledby="ui-preview-title">
      <h1 id="ui-preview-title">공통 UI 미리보기</h1>
      <p>디자인 검토 전 초안 · 가상 상태를 표시합니다.</p>

      <div style={{ display: 'grid', gap: '24px' }}>
        <section aria-labelledby="landing-parts-title">
          <LandingComponentsPreview />
        </section>
        <section aria-labelledby="loading-title">
          <h2 id="loading-title">로딩</h2>
          <StatePanel variant="loading" />
        </section>

        <section aria-labelledby="empty-title">
          <h2 id="empty-title">빈 데이터</h2>
          <StatePanel variant="empty" />
        </section>

        <section aria-labelledby="error-title">
          <h2 id="error-title">오류</h2>
          <StatePanel
            variant="error"
            actionLabel="다시 시도"
            onAction={() => setRetryCount((count) => count + 1)}
          />
          <p role="status">미리보기 버튼 클릭 횟수: {retryCount}</p>
        </section>

        <section aria-labelledby="unauthorized-title">
          <h2 id="unauthorized-title">권한 없음</h2>
          <StatePanel variant="unauthorized" />
        </section>

        <section aria-labelledby="form-preview-title">
          <h2 id="form-preview-title">공통 입력란</h2>

          <div
            style={{
              display: 'grid',
              gap: '24px',
              maxWidth: '480px',
            }}
          >
            <TextField
              label="표시 이름"
              name="preview-name"
              hint="화면에 표시할 이름을 입력해 주세요."
              placeholder="예: 홍길동"
              required
            />

            <TextField
              label="이메일"
              name="preview-email"
              type="email"
              defaultValue="wrong-email"
              error="올바른 이메일 형식으로 입력해 주세요."
              required
            />

            <TextField
              label="수정할 수 없는 항목"
              defaultValue="비활성 상태 예시"
              disabled
            />
          </div>
        </section>

        <section aria-labelledby="form-validation-title">
          <h2 id="form-validation-title">폼 입력 검증</h2>
          <FormPreview />
        </section>

        <section aria-labelledby="table-preview-title">
          <h2 id="table-preview-title">공통 표</h2>
          <TablePreview />
        </section>
      </div>
    </section>
  );
}
